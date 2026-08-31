# Walkthrough - Anomaly Detection Validation on OPSSAT Dataset

We have implemented the standalone validation pipeline for evaluating our anomaly detection ensemble (Gaussian Density Model + Isolation Forest + Logistic Regression Meta-Model) on the `opsatt_dataset.csv` public spacecraft telemetry data.

## Preprocessing & Data Preparation (First Principles)

The features in `opsatt_dataset.csv` represent statistics of telemetry segments across 9 unique channels (sensors). To make this data compatible with our models, we implemented two key preprocessing techniques:
1. **Skewness Correction (Log-Transform):** We applied logarithmic transformations to highly right-skewed positive columns (such as `var`, `std`, `diff_var`, `gaps_squared`, etc.) to stabilize their variance and map their distributions closer to a normal distribution, satisfying the assumptions of the [GaussianDensityModel](file:///c:/Codes/NOVASAT%20REBUILD/novasat-sim/experiments/train_anomaly_models.py#L30-L66).
2. **Channel-Specific Standard Scaling:** Because each telemetry channel represents a different physical sensor (e.g. voltage, temperature) with distinct ranges, standardizing features globally would distort their normal distributions. We standardized the features independently for each channel using the mean and standard deviation of normal training samples of that channel, aligning them all to standard normal scales ($\mu = 0$, $\sigma = 1$).

## Training Pipeline & Leakage Prevention

To prevent data leakage during meta-model training:
- We used a **5-Fold cross-validation** scheme over the training partition (`train == 1`) to generate Out-Of-Fold (OOF) raw anomaly scores for all training samples.
- We fit the StandardScaler and Logistic Regression stacking meta-model on these OOF scores.
- Optimal decision thresholds were chosen on the training scores by maximizing the training F1-score.
- Final base models were trained on 100% of the training normal samples.

## Validation Results (Single-Touch Test Evaluation)

The validation script [opsatt_validation.py](file:///c:/Codes/NOVASAT%20REBUILD/novasat-sim/experiments/opsatt_validation.py) was run against the untouched test partition (`train == 0`). The side-by-side results are:

| Model | F1-Score | Precision | Recall | TP | FP | FN | TN |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Gaussian (EllipticEnv)** | 0.7304 | 0.7179 | 0.7434 | 84 | 33 | 29 | 383 |
| **Isolation Forest** | 0.7328 | 0.7143 | 0.7522 | 85 | 34 | 28 | 382 |
| **Stacking Ensemble** | **0.7382** | **0.7167** | **0.7611** | **86** | **34** | **27** | **382** |

> [!NOTE]
> **Key Validation Takeaway & Statistical Prudence:**
> While the Stacking Ensemble achieves $F1 = 0.7382$ compared to Isolation Forest's $0.7328$, the raw difference amounts to **exactly 1 flipped prediction** ($86$ TP vs. $85$ TP, $27$ FN vs. $28$ FN). As proven by McNemar's test below, this difference is **statistically insignificant** ($p = 1.0000$), meaning the ensemble performs **on par with Isolation Forest**, not statistically superior.

## Statistical Significance & Hypothesis Testing

### 1. McNemar's Test for Paired Predictions (Ensemble vs. Isolation Forest)
To test whether the ensemble's slight edge over Isolation Forest is statistically significant or within noise, we performed McNemar's test on the per-sample predictions of the test set ($N=529$):

| | Stacking Ensemble Correct | Stacking Ensemble Incorrect |
| :--- | :--- | :--- |
| **Isolation Forest Correct** | $n_{00} = 460$ (Both Correct) | $n_{01} = 7$ (iForest Correct, Ensemble Wrong) |
| **Isolation Forest Incorrect** | $n_{10} = 8$ (iForest Wrong, Ensemble Correct) | $n_{11} = 54$ (Both Wrong) |

* **Total Disagreements ($b + c$):** $15$ samples out of $529$
* **McNemar $\chi^2$ (with continuity correction):** $0.0000$
* **Exact Binomial $p$-value:** $\mathbf{1.0000} \quad (p \ge 0.05)$
* **Statistical Conclusion:** **Fail to reject $H_0$.** There is no statistically significant difference between the Stacking Ensemble and Isolation Forest ($p = 1.0000$). Stacking performs on par with the best base model.

### 2. 10,000 Bootstrap Resampling Iterations
We resampled the test set with replacement $10,000$ times to construct empirical 95% Confidence Intervals (2.5th to 97.5th percentiles):
* **OPSSAT Real Flight Test Set ($N=529$):**
  * **F1-Score:** $\mathbf{0.7373} \quad (\text{95\% CI: } [\mathbf{0.6703}, \mathbf{0.7982}], \, \sigma = 0.0325)$
  * **Precision:** $\mathbf{0.7164} \quad (\text{95\% CI: } [0.6330, 0.7949], \, \sigma = 0.0414)$
  * **Recall:** $\mathbf{0.7612} \quad (\text{95\% CI: } [0.6804, 0.8387], \, \sigma = 0.0400)$
* **NOVASAT Simulated Test Set ($N=20,520$):**
  * **F1-Score:** $\mathbf{0.9233} \quad (\text{95\% CI: } [\mathbf{0.9145}, \mathbf{0.9319}], \, \sigma = 0.0044)$
  * **Precision:** $\mathbf{0.9850} \quad (\text{95\% CI: } [0.9793, 0.9902], \, \sigma = 0.0028)$
  * **Recall:** $\mathbf{0.8689} \quad (\text{95\% CI: } [0.8540, 0.8834], \, \sigma = 0.0074)$

### 3. Multi-Seed Model Training Stability Sweep (30 Seeds)
We re-trained and evaluated the OPSSAT pipeline across $30$ different random seeds (varying K-Fold splits and Isolation Forest initializations):
* **Mean F1 across 30 Seeds:** $\mathbf{0.7329} \quad (\sigma = 0.0101)$
* **Min/Max F1 Range:** $[0.7117, 0.7556]$
* **95% Model Seed CI:** $[0.7126, 0.7515]$

### Fitted Stacking Meta-Model Equation

The standardized score conversions and stacking meta-model coefficients are:
$$z_{\text{gaussian}} = \frac{\text{raw\_gaussian} - 0.028593}{0.032150}$$
$$z_{\text{iforest}} = \frac{\text{raw\_iforest} - (-0.051598)}{0.049810}$$
$$P(\text{anomaly}) = \sigma(1.077904 \cdot z_{\text{gaussian}} + 0.059656 \cdot z_{\text{iforest}} - 2.616309)$$

## Model Artifacts

All trained models and preprocessing statistics have been saved to [models/opsatt/](file:///c:/Codes/NOVASAT%20REBUILD/novasat-sim/models/opsatt):
- `gaussian_model.pkl`
- `isolation_forest_model.pkl`
- `ensemble_scaler.pkl`
- `ensemble_meta_model.pkl`
- `preprocess_stats.pkl` (contains channel-specific scaling parameters and optimal thresholds)
