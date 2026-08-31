# TODO List - Anomaly Detection Ensemble on OPSSAT Dataset

- [x] Create `opsatt_validation.py` script.
  - [x] Implement log-transform and per-channel standard scaling.
  - [x] Implement 5-fold cross validation for raw scores generation on training normal data.
  - [x] Implement Logistic Regression meta-model training.
  - [x] Implement decision threshold selection on the training partition.
  - [x] Implement final base model fitting on all normal training data.
  - [x] Implement test partition evaluation.
- [x] Run the validation script on `opsatt_dataset.csv`.
- [x] Record test results and fitted weights.
- [x] Write `walkthrough.md` report.
