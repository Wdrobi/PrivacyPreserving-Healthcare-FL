# Dataset card — UCI Heart Disease

## Intended research use

This project uses the UCI Heart Disease collection as a public benchmark for
institution-aware federated binary classification. Its four processed sources
are mapped to four FL clients:

- Cleveland Clinic Foundation;
- Hungarian Institute of Cardiology, Budapest;
- University Hospital, Zurich, Switzerland;
- VA Medical Center, Long Beach.

The target is `0` for absence and `1` for presence, obtained by mapping the UCI
diagnostic `num` value `0` to absence and values `1` through `4` to presence.

## Source and license

Janosi, A., Steinbrunn, W., Pfisterer, M., & Detrano, R. (1989). *Heart
Disease* [Dataset]. UCI Machine Learning Repository.
https://doi.org/10.24432/C52P4X

The repository marks the dataset as CC BY 4.0. The downloader records the
official URL, retrieval time, file size, and SHA-256 digest in local metadata.

## Features

The standard 13 predictors are `age`, `sex`, `cp`, `trestbps`, `chol`, `fbs`,
`restecg`, `thalach`, `exang`, `oldpeak`, `slope`, `ca`, and `thal`. The archive
uses `?` for missing values.

## Privacy and limitations

The public archive is de-identified and must not be treated as current clinical
care data. Institution membership is retained only as the federated client key;
it is not passed to the model as a predictor. Small site sizes, missingness,
historical collection practices, demographic imbalance, and domain shift limit
clinical generalization. Results are research benchmarks, not diagnostic claims.

