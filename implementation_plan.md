# Test Anomaly Detection Ensemble on OPSSAT Dataset

This plan details how to test our multi-modal anomaly detection ensemble (Gaussian Density Model + Isolation Forest + Logistic Regression Meta-Model) on the `opsatt_dataset.csv` public spacecraft telemetry data. To make the data fit our model parameters (which assume a single, homogeneous normal distribution for the Gaussian Density Model), we will preprocess the dataset by correcting highly skewed features using logarithmic transforms and aligning physical sensors using channel-specific scaling.

## User Review Required

> [!IMPORTANT]
> **Data Preprocessing & Stacking Strategy from First Principles:**
> - **Logarithmic Transformation:** Right-skewed positive features (such as variance, peaks, and squared values) have power-law distributions with long tails. This violates the multivariate normality assumption of the `GaussianDensityModel`. Applying a log-transform stabilizes the variance and maps the distributions closer to symmetric normals.
> - **Per-Channel Scaling:** Telemetry features vary widely in baseline range across physical channels (e.g., voltage vs. temperature). Standardizing features using channel-specific means and standard deviations (computed from training normal data only) aligns all channels to the same standard normal scale ($\mu = 0$, $\sigma = 1$), making their distributions comparable.
> - **Leakage Prevention via K-Fold Stacking:** To train the Logistic Regression meta-model without data leakage, we use a 5-Fold cross-validation pipeline over the training partition (`train == 1`) to generate Out-Of-Fold (OOF) raw scores, rather than wasting 30% of normal training data on a hold-out validation split.

## Open Questions

None. The preprocessing choices are locked and derived from first-principles analysis of the feature distributions and model assumptions.

## Proposed Changes

### Preprocessing and Validation Pipeline

#### [NEW] [opsatt_validation.py](file:///c:/Codes/NOVASAT%20REBUILD/novasat-sim/experiments/opsatt_validation.py)
Create a new standalone validation script to load, preprocess, train, and evaluate the anomaly detection pipeline on the `opsatt_dataset.csv`.

The script will:
1. Load `opsatt_dataset.csv` from [data/opsatt_dataset.csv](file:///c:/Codes/NOVASAT%20REBUILD/novasat-sim/data/opsatt_dataset.csv).
2. Cast feature columns to `float64` and apply log-transforms to highly right-skewed features.
3. Compute channel-specific means and standard deviations from normal training samples (`train == 1` and `anomaly == 0`), standardizing features independently for each channel.
4. Implement a 5-Fold cross-validation pipeline to generate out-of-fold Gaussian and Isolation Forest raw anomaly scores on the training partition.
5. Standardize raw scores and train a Logistic Regression meta-model to compute combined anomaly probabilities.
6. Select optimal decision thresholds for all three models using the training scores.
7. Fit final base models on 100% of the training normal samples.
8. Evaluate all models on the untouched test partition (`train == 0`).
9. Output side-by-side performance metrics (F1-score, Precision, Recall, Confusion Matrix) and print the fitted meta-model equation.

## Verification Plan

### Automated Tests
We will run the new validation script directly using the virtual environment interpreter to train the models and output final test performance metrics:
```powershell
.venv\Scripts\python.exe experiments/opsatt_validation.py
```
We will verify that:
1. The script completes successfully with zero errors.
2. The Stacking Ensemble F1-score beats both the Gaussian model and the Isolation Forest model individual baselines.
3. The final meta-model weights and bias are printed out explicitly.
