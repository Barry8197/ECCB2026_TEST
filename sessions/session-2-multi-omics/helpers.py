"""
Utilities for From Multi-Omics to Gene–Disease Discovery: Knowledge Graphs and LLM-Augmented Analysis Tutorial at ECCB 2026 Geneva.

Functions exported
- load_omics
- evaluate_predictions
- plot_confusion_matrix
- generate_diagnostic_plots
- build_mofa_matrix_input
- fit_mofa
- select_active_factors
- project_test_patients_to_mofa_factors
- eta_squared_by_factor
- fit_factor_classifier
- plot_r2_heatmap
- plot_factor_boxplots_by_subtype
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    ConfusionMatrixDisplay
)
from sklearn.linear_model import LogisticRegression

from mofapy2.run.entry_point import entry_point
import mofax as mfx

__all__ = [
    "load_omics",
    "evaluate_predictions",
    "plot_confusion_matrix",
    "generate_diagnostic_plots",
    "build_mofa_matrix_input",
    "fit_mofa", 
    "select_active_factors",
    "project_test_patients_to_mofa_factors",
    "eta_squared_by_factor",
    "fit_factor_classifier",
    "plot_r2_heatmap",
    "plot_factor_boxplots_by_subtype",
]

# ---------------------------------------------------------------------------
# SESSION - 2 - LLM Functions
# ---------------------------------------------------------------------------

def build_mofa_matrix_input(X_by_omic):
    """Convert aligned omics DataFrames to the nested matrix format expected by mofapy2.

    mofapy2 expects data[view][group] = samples x features. This example uses a
    single group ("TCGA-BRCA_train") and one entry per omics view.
    """
    data, view_names, feature_names = [], [], []
    mofa_sample_ids = next(iter(X_by_omic.values())).index.astype(str)

    for view_name, X in X_by_omic.items():
        assert X.index.astype(str).equals(mofa_sample_ids), f"Patient index differs in {view_name}"
        view_names.append(view_name)
        feature_names.append(X.columns.astype(str).tolist())
        data.append([X.to_numpy(dtype=np.float32)])  # one group, many views

    sample_names = [mofa_sample_ids.tolist()]
    group_names = ["TCGA-BRCA_train"]

    return data, view_names, feature_names, sample_names, group_names

def fit_mofa(data, view_names, feature_names, sample_names, group_names,
             max_factors, iterations, random_state, outfile):
    """Fit a compact MOFA model with mofapy2 and return the trained entry point object.

    Uses factor-level ARD so the model can automatically shrink factors that
    explain little signal; the caller later keeps only the "active" factors
    based on the fitted model's variance-explained (R2) table.
    """
    model = entry_point()

    model.set_data_options(
        scale_views=True,
        scale_groups=False,
        center_groups=True,
        use_float32=True,
    )

    model.set_data_matrix(
        data=data,
        likelihoods=["gaussian"] * len(view_names),
        views_names=view_names,
        groups_names=group_names,
        samples_names=sample_names,
        features_names=feature_names,
    )

    model.set_model_options(
        factors=max_factors,
        spikeslab_factors=False,
        spikeslab_weights=True,
        ard_factors=True,
        ard_weights=True,
    )

    model.set_train_options(
        iter=iterations,
        convergence_mode="fast",
        seed=random_state,
        verbose=False,
        quiet=True,
        outfile=str(outfile),
    )

    model.build()
    model.run()

    if not Path(outfile).exists():
        model.save(outfile=str(outfile))

    return model

def select_active_factors(mofa_model_mfx, min_total_r2, max_factors):
    """Select 'active' MOFA factors using the fitted model's variance-explained (R2) table.

    Sums each factor's R2 across all omics views and keeps factors whose total R2
    is at least `min_total_r2`. Falls back to the single best factor if none pass.

    Returns
    -------
    active_factor_cols : list[str]
        Factor names (e.g. "Factor1") to keep for downstream analysis.
    factor_r2_summary : pd.DataFrame
        Total R2 per factor, sorted descending.
    """
    r2_all = mofa_model_mfx.get_r2().rename(
        columns={"Factor": "factor", "View": "view", "Group": "group_mofax", "R2": "r2"}
    )

    factor_r2_summary = (
        r2_all.groupby("factor", as_index=False)["r2"].sum()
        .rename(columns={"r2": "total_r2"})
        .sort_values("total_r2", ascending=False)
    )

    active_factor_summary = factor_r2_summary[factor_r2_summary["total_r2"] >= min_total_r2].copy()
    if active_factor_summary.empty:
        active_factor_summary = factor_r2_summary.head(1).copy()

    active_factor_cols = active_factor_summary["factor"].tolist()
    return active_factor_cols, factor_r2_summary

def project_test_patients_to_mofa_factors(model, X_train_by_view, X_test_by_view,
                                           train_factors, view_names):
    """Project held-out patients into the fixed MOFA factor space.

    MOFA is fitted on training patients only. To evaluate on held-out patients we
    keep the learned weights (W) fixed and estimate each test patient's factor
    values via a pseudo-inverse projection, then calibrate the projection to the
    factor scale returned by the trained model. All calibration is fit on
    training patients only.
    """
    factor_columns = train_factors.columns.astype(str).tolist()
    projected_test_by_view = []

    for view_name in view_names:
        weights = model.get_weights(views=view_name, df=True)
        weights.columns = weights.columns.astype(str)
        weights = weights.reindex(columns=factor_columns)

        common_features = weights.index.intersection(X_train_by_view[view_name].columns)
        common_features = common_features.intersection(X_test_by_view[view_name].columns)
        weights = weights.loc[common_features]

        X_train_view = X_train_by_view[view_name].loc[:, common_features].astype(float)
        X_test_view = X_test_by_view[view_name].loc[:, common_features].astype(float)
        X_train_view.index = X_train_view.index.astype(str)
        X_test_view.index = X_test_view.index.astype(str)

        train_mean = X_train_view.mean(axis=0)
        train_std = X_train_view.std(axis=0, ddof=0).replace(0, 1)
        X_train_scaled = (X_train_view - train_mean) / train_std
        X_test_scaled = (X_test_view - train_mean) / train_std

        raw_train_projection = X_train_scaled.to_numpy() @ np.linalg.pinv(weights.to_numpy()).T
        raw_test_projection = X_test_scaled.to_numpy() @ np.linalg.pinv(weights.to_numpy()).T

        train_design = np.column_stack([raw_train_projection, np.ones(raw_train_projection.shape[0])])
        test_design = np.column_stack([raw_test_projection, np.ones(raw_test_projection.shape[0])])
        train_target = train_factors.loc[X_train_view.index, factor_columns].to_numpy()
        calibration = np.linalg.lstsq(train_design, train_target, rcond=None)[0]
        projected_values = test_design @ calibration

        projected = pd.DataFrame(projected_values, index=X_test_view.index, columns=factor_columns)
        projected_test_by_view.append(projected)

    return sum(projected_test_by_view) / len(projected_test_by_view)

def eta_squared_by_factor(factor_table, labels):
    """Compute one-way ANOVA eta-squared for each factor (fraction of factor variance
    explained by subtype group membership), without fitting a predictive model.
    """
    rows = []
    labels = labels.astype(str)

    for factor in factor_table.columns:
        values = factor_table[factor]
        grand_mean = values.mean()
        ss_total = ((values - grand_mean) ** 2).sum()
        ss_between = 0.0

        for _, idx in labels.groupby(labels).groups.items():
            group_values = values.loc[idx]
            ss_between += len(group_values) * (group_values.mean() - grand_mean) ** 2

        eta2 = ss_between / ss_total if ss_total > 0 else np.nan
        rows.append({"factor": factor, "eta_squared": eta2})

    return pd.DataFrame(rows).sort_values("eta_squared", ascending=False)

def fit_factor_classifier(factors_df, y, train_ids, test_ids, model_name):
    """Fit a logistic regression classifier on training factors and evaluate on
    held-out test factors. Uses only the MOFA factor values (Z), not the raw
    omics matrices, as a diagnostic of whether the learned representation
    preserves subtype information.
    """
    clf = LogisticRegression(
        max_iter=2000,
        class_weight="balanced",
        random_state=42,
    )
    clf.fit(factors_df.loc[train_ids], y.loc[train_ids])
    pred = clf.predict(factors_df.loc[test_ids])
    metrics = evaluate_predictions(y.loc[test_ids], pred, model_name)
    return clf, pred, metrics

def plot_r2_heatmap(r2_all, view_names, active_factor_cols, output_path):
    """Draw and save an annotated heatmap of MOFA variance explained (R2).

    Rows are omics views, columns are the selected "active" factors, and each
    cell is the percentage of that view's variance reconstructed by that
    factor. This is the standard first diagnostic for a fitted MOFA model:
    it shows which views each factor is associated with before inspecting
    patient-level factor values or feature weights.
    """
    r2_heatmap = (
        r2_all[r2_all["factor"].isin(active_factor_cols)]
        .pivot(index="view", columns="factor", values="r2")
        .reindex(index=view_names, columns=active_factor_cols)
    )

    fig, ax = plt.subplots(figsize=(1.1 * len(active_factor_cols) + 3, 3.6))
    im = ax.imshow(r2_heatmap, aspect="auto", cmap="Blues")

    ax.set_title("MOFA R2 heatmap: views x active factors")
    ax.set_xlabel("MOFA factor")
    ax.set_ylabel("Omics view")
    ax.set_xticks(range(r2_heatmap.shape[1]))
    ax.set_xticklabels(r2_heatmap.columns, rotation=45, ha="right")
    ax.set_yticks(range(r2_heatmap.shape[0]))
    ax.set_yticklabels(r2_heatmap.index)

    for row in range(r2_heatmap.shape[0]):
        for col in range(r2_heatmap.shape[1]):
            value = r2_heatmap.iloc[row, col]
            if pd.notna(value):
                ax.text(col, row, f"{value:.1f}", ha="center", va="center", fontsize=8)

    fig.colorbar(im, ax=ax, label="MOFA R2 (%)")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)

def plot_factor_boxplots_by_subtype(factors_df, train_ids, y_train, top_factors, output_path):
    """Draw and save boxplots of the top subtype-associated MOFA factor values.

    Uses training patients only (matching the eta-squared ranking they were
    selected from). One panel per factor; each panel shows the distribution
    of that factor's values, split out by subtype, to make it easy to see
    which subtypes are shifted relative to one another on that latent axis.
    """
    train_factors_for_plot = factors_df.loc[train_ids.astype(str), top_factors]
    train_labels_for_plot = y_train.astype(str)
    subtypes = train_labels_for_plot.dropna().unique()

    n_panels = len(top_factors)
    fig, axes = plt.subplots(1, n_panels, figsize=(3.75 * n_panels, 4), squeeze=False)

    for ax, factor in zip(axes.ravel(), top_factors):
        groups = [
            train_factors_for_plot.loc[train_labels_for_plot == subtype, factor].dropna()
            for subtype in subtypes
        ]
        ax.boxplot(groups, tick_labels=subtypes, showfliers=False)
        ax.set_title(factor)
        ax.set_ylabel("Factor value")
        ax.tick_params(axis="x", rotation=45)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)

def plot_ranked_feature_weights(mofa_model_mfx, ranked_factors, view, output_path, n_features=5):
    """Draw and save ranked, signed feature-weight plots for one omics view.

    For each of `ranked_factors`, ranks that view's features by signed MOFA
    weight and plots the curve, labelling the top `n_features` at each tail.
    Features far from zero define the factor most strongly; this makes the
    strongest positive- and negative-contributing features easy to spot for
    each factor.
    """
    fig, axes = plt.subplots(1, len(ranked_factors), figsize=(5 * len(ranked_factors), 4.5), squeeze=False)

    for ax, ranked_factor in zip(axes.ravel(), ranked_factors):
        mfx.plot_weights_ranked(
            mofa_model_mfx,
            factor=ranked_factor,
            view=view,
            n_features=n_features,
            ax=ax,
        )
        ax.set_title(f"{view}: {ranked_factor}")

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)

def generate_diagnostic_plots(mofa_model_mfx, factors_df, factor_r2_summary, view_names,
                               active_factor_cols, factor_subtype_assoc, train_ids, y_train,
                               y_test, mofa_pred, output_dir, top_view_for_weights="transcriptomics"):
    """Generate and save the core MOFA diagnostic plots from the notebook.

    This is a single entry point that wraps four complementary diagnostics,
    each saved as its own PNG file under `output_dir`:

    1. R2 heatmap        -- which omics views each active factor reconstructs.
    2. Factor boxplots    -- how the top subtype-associated factors vary by subtype
                              (training patients only).
    3. Confusion matrix   -- held-out subtype prediction errors from the
                              MOFA-factor logistic regression classifier.
    4. Ranked feature weights -- top positive/negative loadings in
                              `top_view_for_weights` for the top subtype-associated
                              factors.

    Together these mirror the notebook's "R2 -> factor values (Z) -> weights (W)"
    interpretation flow, condensed to one representative plot per stage rather
    than every plot variant shown in the notebook.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)

    # Recreate the "all views x all factors" R2 table used by the heatmap.
    r2_all = mofa_model_mfx.get_r2().rename(
        columns={"Factor": "factor", "View": "view", "Group": "group_mofax", "R2": "r2"}
    )

    plot_r2_heatmap(
        r2_all, view_names, active_factor_cols,
        output_dir / "part2_mofa_r2_heatmap.png",
    )

    top_factors = factor_subtype_assoc.head(4)["factor"].tolist()

    plot_factor_boxplots_by_subtype(
        factors_df, train_ids, y_train, top_factors,
        output_dir / "part2_mofa_factor_boxplots.png",
    )

    plot_confusion_matrix(
        y_test, mofa_pred
    )

    plot_ranked_feature_weights(
        mofa_model_mfx, top_factors[:3], top_view_for_weights,
        output_dir / "part2_mofa_ranked_weights.png",
    )

    print(f"Saved diagnostic plots to: {output_dir}")

# ---------------------------------------------------------------------------
# SESSION - 2 - General Functions
# ---------------------------------------------------------------------------

def plot_confusion_matrix(y_test, y_pred):
    """Draw and save a confusion matrix for the held-out subtype predictions.

    Shows how predicted subtypes (from the MOFA-factor logistic regression
    classifier) compare with true subtypes on the test set, making it easy to
    see which subtypes are most often confused with each other.
    """
    fig, ax = plt.subplots(figsize=(5, 5))
    ConfusionMatrixDisplay.from_predictions(y_test, y_pred, xticks_rotation=45, ax=ax)
    ax.set_title("Confusion matrix — MOFA factors")
    fig.tight_layout()
    plt.show()

def evaluate_predictions(y_true: np.ndarray, y_pred: np.ndarray, title: str) -> None:
    """Summarise classification performance by printing common evaluation metrics.

    This utility prints:
      - A header using `title`
      - Overall accuracy (`accuracy_score`)
      - Balanced accuracy (`balanced_accuracy_score`)
      - A full per-class report (`classification_report`), including precision,
        recall, f1-score, and support.

    Notes
    -----
    - `y_true` and `y_pred` should be 1D arrays of the same length containing
      class labels (typically integer-encoded).

    Parameters
    ----------
    y_true
        Ground-truth class labels.
    y_pred
        Predicted class labels.
    title
        Title printed above the metric summary (useful for distinguishing
        train/validation/test outputs).
    """
    sep = "─" * len(title)
    accuracy = accuracy_score(y_true, y_pred)
    balanced_accuracy =  balanced_accuracy_score(y_true, y_pred)
    print(f"\n{title}\n{sep}")
    print(f"  Accuracy          : {accuracy:.3f} ")
    print(f"  Balanced accuracy : {balanced_accuracy:.3f}")
    print()
    plot_confusion_matrix(y_true, y_pred)

    return {
        "model": title,
        "accuracy": accuracy,
        "balanced_accuracy": balanced_accuracy,
    }

def load_omics(
    data_dir: str | Path,
    omic_keys: Sequence[str],
) -> tuple[dict[str, pd.DataFrame], pd.Series]:
    """Load TCGA-BRCA multi-omics views and subtype labels from a pickled bundle.

    Reads `omics.pkl` from `data_dir`. The pickle is expected to contain a dict-like
    object with:
      - one table per omic view specified by `omic_keys` (each a pd.DataFrame)
      - a label vector under the key `"meta"` (pd.Series or similar)

    The function:
    1) loads the pickle
    2) checks required keys exist (all `omic_keys` plus `"meta"`)
    3) prints the shape of each requested omics view
    4) verifies all requested omics tables share an identical patient index
    5) returns a dict of feature matrices (X_views) and the labels (y)

    Parameters
    ----------
    data_dir
        Directory containing `omics.pkl`.
    omic_keys
        Required. Names of the omics views to load (e.g.
        `["transcriptomics", "proteomics", "methylation"]`).

    Returns
    -------
    X_views
        Mapping from each key in `omic_keys` to a copy of its feature matrix.
    y
        Copy of the target labels (subtype) indexed by patient ID.

    Raises
    ------
    FileNotFoundError
        If `omics.pkl` is not found in `data_dir`.
    ValueError
        If `omic_keys` is empty, or if patient indices across omics views are not identical.
    KeyError
        If any required key is missing from the pickle contents.
    """
    data_dir = Path(data_dir)

    if omic_keys is None or len(omic_keys) == 0:
        raise ValueError("omic_keys is required and must contain at least one key.")

    # ---- Load the bundle -------------------------------------------------
    omics_path = data_dir / "omics.pkl"
    if not omics_path.exists():
        raise FileNotFoundError(f"omics.pkl not found in: {data_dir}")

    omics = pd.read_pickle(omics_path)

    # ---- Validate expected keys -----------------------------------------
    required = list(omic_keys) + ["meta"]
    missing = [k for k in required if k not in omics]
    if missing:
        raise KeyError(f"Missing keys in omics.pkl: {missing}")

    # ---- Print dimensions (quick sanity check) --------------------------
    print("Omic view dimensions:")
    for key in omic_keys:
        n_patients, n_features = omics[key].shape
        print(f"  {key:15s}: {n_patients:4d} patients × {n_features:6d} features")

    # ---- Assert alignment across requested views ------------------------
    reference_index = omics[omic_keys[0]].index
    for key in omic_keys[1:]:
        if not reference_index.equals(omics[key].index):
            raise ValueError(
                f"Patient index of '{key}' does not match '{omic_keys[0]}'. "
                "Views must be pre-aligned."
            )

    # ---- Build outputs ---------------------------------------------------
    X_views = {key: omics[key].copy() for key in omic_keys}
    y = omics["meta"].copy()

    # ---- Optional: label distribution (nice in notebooks) ---------------
    print("\nSubtype counts:")
    display(y.value_counts())

    return X_views, y