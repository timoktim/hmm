# Stage03V RERUN1 Fold Plan Magnitude Overview

- index_id: STAGE03V-RERUN1-v1
- status: pass
- source_db_path: data/db/a_share_hmm_tushare_v7.duckdb
- v7_coverage_available: yes
- sw2021_l2_universe_coverage: pass
- fold_plan_path: reports/stage03v/purge_embargo_fold_plan_v2.json

## Magnitude Overview

- fold_plan_source: full_labeled_historical_development_rows
- fold_count: 10
- validation_start_date: 2016-01-04
- validation_end_date: 2026-06-08
- total_validation_trade_dates: 2531
- validation_date_span_ratio: 0.8386173491853809
- min_fold_validation_trade_dates: 253
- min_fold_slice_train_rows: 57479
- prospective_holdout_label_consumed_count: 0

| fold_id | train_start | train_end | validation_start | validation_end | validation_dates | train_rows | validation_rows | min_slice_train_rows |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fold_1 | 2014-01-02 | 2015-12-31 | 2016-01-04 | 2017-01-16 | 254 | 1179592 | 626620 | 57479 |
| fold_2 | 2014-01-02 | 2017-01-16 | 2017-01-17 | 2018-01-26 | 253 | 1806056 | 627440 | 88790 |
| fold_3 | 2014-01-02 | 2018-01-26 | 2018-01-29 | 2019-02-18 | 253 | 2433496 | 627440 | 120162 |
| fold_4 | 2014-01-02 | 2019-02-18 | 2019-02-19 | 2020-03-03 | 253 | 3060936 | 627440 | 151534 |
| fold_5 | 2014-01-02 | 2020-03-03 | 2020-03-04 | 2021-03-17 | 253 | 3688376 | 627440 | 182906 |
| fold_6 | 2014-01-02 | 2021-03-17 | 2021-03-18 | 2022-03-31 | 253 | 4315816 | 627440 | 214278 |
| fold_7 | 2014-01-02 | 2022-03-31 | 2022-04-01 | 2023-04-17 | 253 | 4943256 | 627440 | 245650 |
| fold_8 | 2014-01-02 | 2023-04-17 | 2023-04-18 | 2024-05-07 | 253 | 5570696 | 627440 | 277022 |
| fold_9 | 2014-01-02 | 2024-05-07 | 2024-05-08 | 2025-05-22 | 253 | 6198136 | 627440 | 308394 |
| fold_10 | 2014-01-02 | 2025-05-22 | 2025-05-23 | 2026-06-08 | 253 | 6825576 | 610576 | 339766 |

## Hard Gates

- fold_count_between_8_and_10: pass
- validation_date_span_ge_60pct_development_span: pass
- total_validation_trade_dates_ge_500: pass
- per_fold_per_slice_train_rows_ge_5000: pass
- per_fold_validation_trade_dates_ge_200: pass
- prospective_holdout_label_consumed_count_eq_0: pass
- purge_violation_count_eq_0: pass
- embargo_violation_count_eq_0: pass

## Fold Slice Evidence

| fold_id | slice_id | train_rows | validation_rows | positives | market_blocks | idiosyncratic_episodes |
|---|---|---:|---:|---:|---:|---:|
| fold_1 | h1:fixed:0.0300:diagnostic_only | 59816 | 31331 | 2245 | 14 | 145 |
| fold_1 | h1:fixed:0.0500:diagnostic_only | 59816 | 31331 | 1119 | 10 | 81 |
| fold_1 | h1:fixed:0.0800:diagnostic_only | 59816 | 31331 | 366 | 3 | 16 |
| fold_1 | h1:fixed:0.1000:diagnostic_only | 59816 | 31331 | 13 | 0 | 10 |
| fold_1 | h3:fixed:0.0300:diagnostic_only | 59570 | 31331 | 6032 | 13 | 153 |
| fold_1 | h3:fixed:0.0500:diagnostic_only | 59570 | 31331 | 3417 | 9 | 75 |
| fold_1 | h3:fixed:0.0800:diagnostic_only | 59570 | 31331 | 1220 | 5 | 82 |
| fold_1 | h3:fixed:0.1000:diagnostic_only | 59570 | 31331 | 623 | 4 | 17 |
| fold_1 | h5:fixed:0.0300:eligible | 59324 | 31331 | 8315 | 9 | 100 |
| fold_1 | h5:fixed:0.0500:eligible | 59324 | 31331 | 5028 | 8 | 90 |
| fold_1 | h5:fixed:0.0800:eligible | 59324 | 31331 | 2343 | 7 | 59 |
| fold_1 | h5:fixed:0.1000:eligible | 59324 | 31331 | 1510 | 4 | 54 |
| fold_1 | h10:fixed:0.0300:eligible | 58709 | 31331 | 12372 | 5 | 43 |
| fold_1 | h10:fixed:0.0500:eligible | 58709 | 31331 | 8222 | 7 | 26 |
| fold_1 | h10:fixed:0.0800:eligible | 58709 | 31331 | 4153 | 5 | 30 |
| fold_1 | h10:fixed:0.1000:eligible | 58709 | 31331 | 2741 | 3 | 51 |
| fold_1 | h20:fixed:0.0300:diagnostic_only | 57479 | 31331 | 16156 | 2 | 1 |
| fold_1 | h20:fixed:0.0500:eligible | 57479 | 31331 | 11808 | 2 | 2 |
| fold_1 | h20:fixed:0.0800:eligible | 57479 | 31331 | 6600 | 4 | 15 |
| fold_1 | h20:fixed:0.1000:eligible | 57479 | 31331 | 4400 | 4 | 39 |
| fold_2 | h1:fixed:0.0300:diagnostic_only | 91146 | 31372 | 910 | 9 | 253 |
| fold_2 | h1:fixed:0.0500:diagnostic_only | 91146 | 31372 | 185 | 1 | 92 |
| fold_2 | h1:fixed:0.0800:diagnostic_only | 91146 | 31372 | 38 | 0 | 29 |
| fold_2 | h1:fixed:0.1000:diagnostic_only | 91146 | 31372 | 15 | 0 | 13 |
| fold_2 | h3:fixed:0.0300:diagnostic_only | 90898 | 31372 | 4183 | 12 | 181 |
| fold_2 | h3:fixed:0.0500:diagnostic_only | 90898 | 31372 | 1251 | 8 | 145 |
| fold_2 | h3:fixed:0.0800:diagnostic_only | 90898 | 31372 | 193 | 0 | 101 |
| fold_2 | h3:fixed:0.1000:diagnostic_only | 90898 | 31372 | 50 | 0 | 26 |
| fold_2 | h5:fixed:0.0300:eligible | 90650 | 31372 | 7105 | 9 | 130 |
| fold_2 | h5:fixed:0.0500:eligible | 90650 | 31372 | 3087 | 9 | 101 |
| fold_2 | h5:fixed:0.0800:eligible | 90650 | 31372 | 698 | 4 | 97 |
| fold_2 | h5:fixed:0.1000:eligible | 90650 | 31372 | 205 | 1 | 66 |
| fold_2 | h10:fixed:0.0300:eligible | 90030 | 31372 | 11892 | 3 | 44 |
| fold_2 | h10:fixed:0.0500:eligible | 90030 | 31372 | 6788 | 4 | 55 |
| fold_2 | h10:fixed:0.0800:eligible | 90030 | 31372 | 2836 | 5 | 36 |
| fold_2 | h10:fixed:0.1000:eligible | 90030 | 31372 | 1451 | 5 | 28 |
| fold_2 | h20:fixed:0.0300:diagnostic_only | 88790 | 31372 | 16809 | 1 | 2 |
| fold_2 | h20:fixed:0.0500:eligible | 88790 | 31372 | 12383 | 2 | 12 |
| fold_2 | h20:fixed:0.0800:eligible | 88790 | 31372 | 7517 | 3 | 15 |
| fold_2 | h20:fixed:0.1000:eligible | 88790 | 31372 | 5114 | 4 | 19 |
| fold_3 | h1:fixed:0.0300:diagnostic_only | 122518 | 31372 | 1716 | 18 | 234 |
| fold_3 | h1:fixed:0.0500:diagnostic_only | 122518 | 31372 | 508 | 4 | 111 |
| fold_3 | h1:fixed:0.0800:diagnostic_only | 122518 | 31372 | 92 | 2 | 11 |
| fold_3 | h1:fixed:0.1000:diagnostic_only | 122518 | 31372 | 0 | 0 | 0 |
| fold_3 | h3:fixed:0.0300:diagnostic_only | 122270 | 31372 | 6629 | 16 | 150 |
| fold_3 | h3:fixed:0.0500:diagnostic_only | 122270 | 31372 | 2690 | 10 | 104 |
| fold_3 | h3:fixed:0.0800:diagnostic_only | 122270 | 31372 | 764 | 3 | 70 |
| fold_3 | h3:fixed:0.1000:diagnostic_only | 122270 | 31372 | 283 | 2 | 33 |
| fold_3 | h5:fixed:0.0300:eligible | 122022 | 31372 | 10032 | 8 | 48 |
| fold_3 | h5:fixed:0.0500:eligible | 122022 | 31372 | 5076 | 12 | 117 |
| fold_3 | h5:fixed:0.0800:eligible | 122022 | 31372 | 1973 | 6 | 73 |
| fold_3 | h5:fixed:0.1000:eligible | 122022 | 31372 | 1085 | 3 | 51 |
| fold_3 | h10:fixed:0.0300:eligible | 121402 | 31372 | 15621 | 4 | 4 |
| fold_3 | h10:fixed:0.0500:eligible | 121402 | 31372 | 9720 | 6 | 4 |
| fold_3 | h10:fixed:0.0800:eligible | 121402 | 31372 | 4435 | 8 | 55 |
| fold_3 | h10:fixed:0.1000:eligible | 121402 | 31372 | 2902 | 4 | 75 |
| fold_3 | h20:fixed:0.0300:diagnostic_only | 120162 | 31372 | 21238 | 1 | 2 |
| fold_3 | h20:fixed:0.0500:eligible | 120162 | 31372 | 15975 | 1 | 0 |
| fold_3 | h20:fixed:0.0800:eligible | 120162 | 31372 | 8890 | 2 | 0 |
| fold_3 | h20:fixed:0.1000:eligible | 120162 | 31372 | 6256 | 5 | 49 |
| fold_4 | h1:fixed:0.0300:diagnostic_only | 153890 | 31372 | 1484 | 12 | 232 |
| fold_4 | h1:fixed:0.0500:diagnostic_only | 153890 | 31372 | 432 | 4 | 57 |
| fold_4 | h1:fixed:0.0800:diagnostic_only | 153890 | 31372 | 143 | 2 | 4 |
| fold_4 | h1:fixed:0.1000:diagnostic_only | 153890 | 31372 | 14 | 0 | 14 |
| fold_4 | h3:fixed:0.0300:diagnostic_only | 153642 | 31372 | 5073 | 17 | 180 |
| fold_4 | h3:fixed:0.0500:diagnostic_only | 153642 | 31372 | 1929 | 7 | 227 |
| fold_4 | h3:fixed:0.0800:diagnostic_only | 153642 | 31372 | 669 | 3 | 36 |
| fold_4 | h3:fixed:0.1000:diagnostic_only | 153642 | 31372 | 401 | 2 | 21 |
| fold_4 | h5:fixed:0.0300:eligible | 153394 | 31372 | 7837 | 10 | 72 |
| fold_4 | h5:fixed:0.0500:eligible | 153394 | 31372 | 3618 | 10 | 182 |
| fold_4 | h5:fixed:0.0800:eligible | 153394 | 31372 | 1417 | 3 | 92 |
| fold_4 | h5:fixed:0.1000:eligible | 153394 | 31372 | 903 | 2 | 41 |
| fold_4 | h10:fixed:0.0300:eligible | 152774 | 31372 | 12325 | 4 | 10 |
| fold_4 | h10:fixed:0.0500:eligible | 152774 | 31372 | 6881 | 6 | 45 |
| fold_4 | h10:fixed:0.0800:eligible | 152774 | 31372 | 3086 | 5 | 88 |
| fold_4 | h10:fixed:0.1000:eligible | 152774 | 31372 | 2174 | 2 | 79 |
| fold_4 | h20:fixed:0.0300:diagnostic_only | 151534 | 31372 | 17036 | 1 | 0 |
| fold_4 | h20:fixed:0.0500:eligible | 151534 | 31372 | 12187 | 3 | 1 |
| fold_4 | h20:fixed:0.0800:eligible | 151534 | 31372 | 6937 | 4 | 12 |
| fold_4 | h20:fixed:0.1000:eligible | 151534 | 31372 | 5118 | 2 | 79 |
| fold_5 | h1:fixed:0.0300:diagnostic_only | 185262 | 31372 | 1344 | 11 | 402 |
| fold_5 | h1:fixed:0.0500:diagnostic_only | 185262 | 31372 | 215 | 3 | 117 |
| fold_5 | h1:fixed:0.0800:diagnostic_only | 185262 | 31372 | 5 | 0 | 5 |
| fold_5 | h1:fixed:0.1000:diagnostic_only | 185262 | 31372 | 0 | 0 | 0 |
| fold_5 | h3:fixed:0.0300:diagnostic_only | 185014 | 31372 | 5748 | 18 | 170 |
| fold_5 | h3:fixed:0.0500:diagnostic_only | 185014 | 31372 | 2009 | 9 | 287 |
| fold_5 | h3:fixed:0.0800:diagnostic_only | 185014 | 31372 | 268 | 2 | 107 |
| fold_5 | h3:fixed:0.1000:diagnostic_only | 185014 | 31372 | 51 | 0 | 44 |
| fold_5 | h5:fixed:0.0300:eligible | 184766 | 31372 | 9015 | 8 | 91 |
| fold_5 | h5:fixed:0.0500:eligible | 184766 | 31372 | 3938 | 12 | 180 |
| fold_5 | h5:fixed:0.0800:eligible | 184766 | 31372 | 800 | 3 | 179 |
| fold_5 | h5:fixed:0.1000:eligible | 184766 | 31372 | 247 | 1 | 94 |
| fold_5 | h10:fixed:0.0300:eligible | 184146 | 31372 | 13547 | 2 | 32 |
| fold_5 | h10:fixed:0.0500:eligible | 184146 | 31372 | 7558 | 5 | 38 |
| fold_5 | h10:fixed:0.0800:eligible | 184146 | 31372 | 2416 | 4 | 160 |
| fold_5 | h10:fixed:0.1000:eligible | 184146 | 31372 | 1111 | 2 | 131 |
| fold_5 | h20:fixed:0.0300:diagnostic_only | 182906 | 31372 | 17129 | 1 | 0 |
| fold_5 | h20:fixed:0.0500:eligible | 182906 | 31372 | 11383 | 2 | 5 |
| fold_5 | h20:fixed:0.0800:eligible | 182906 | 31372 | 5190 | 4 | 40 |
| fold_5 | h20:fixed:0.1000:eligible | 182906 | 31372 | 2812 | 3 | 86 |
| fold_6 | h1:fixed:0.0300:diagnostic_only | 216634 | 31372 | 1213 | 7 | 493 |
| fold_6 | h1:fixed:0.0500:diagnostic_only | 216634 | 31372 | 216 | 1 | 123 |
| fold_6 | h1:fixed:0.0800:diagnostic_only | 216634 | 31372 | 7 | 0 | 7 |
| fold_6 | h1:fixed:0.1000:diagnostic_only | 216634 | 31372 | 0 | 0 | 0 |
| fold_6 | h3:fixed:0.0300:diagnostic_only | 216386 | 31372 | 4893 | 19 | 346 |
| fold_6 | h3:fixed:0.0500:diagnostic_only | 216386 | 31372 | 1762 | 5 | 273 |
| fold_6 | h3:fixed:0.0800:diagnostic_only | 216386 | 31372 | 312 | 1 | 124 |
| fold_6 | h3:fixed:0.1000:diagnostic_only | 216386 | 31372 | 82 | 0 | 48 |
| fold_6 | h5:fixed:0.0300:eligible | 216138 | 31372 | 7845 | 10 | 114 |
| fold_6 | h5:fixed:0.0500:eligible | 216138 | 31372 | 3510 | 6 | 308 |
| fold_6 | h5:fixed:0.0800:eligible | 216138 | 31372 | 901 | 4 | 93 |
| fold_6 | h5:fixed:0.1000:eligible | 216138 | 31372 | 284 | 0 | 111 |
| fold_6 | h10:fixed:0.0300:eligible | 215518 | 31372 | 12353 | 3 | 21 |
| fold_6 | h10:fixed:0.0500:eligible | 215518 | 31372 | 7203 | 7 | 109 |
| fold_6 | h10:fixed:0.0800:eligible | 215518 | 31372 | 2936 | 4 | 95 |
| fold_6 | h10:fixed:0.1000:eligible | 215518 | 31372 | 1555 | 4 | 87 |
| fold_6 | h20:fixed:0.0300:diagnostic_only | 214278 | 31372 | 17258 | 1 | 0 |
| fold_6 | h20:fixed:0.0500:eligible | 214278 | 31372 | 12384 | 3 | 7 |
| fold_6 | h20:fixed:0.0800:eligible | 214278 | 31372 | 7129 | 3 | 60 |
| fold_6 | h20:fixed:0.1000:eligible | 214278 | 31372 | 4788 | 3 | 35 |
| fold_7 | h1:fixed:0.0300:diagnostic_only | 248006 | 31372 | 1341 | 11 | 318 |
| fold_7 | h1:fixed:0.0500:diagnostic_only | 248006 | 31372 | 249 | 1 | 106 |
| fold_7 | h1:fixed:0.0800:diagnostic_only | 248006 | 31372 | 49 | 1 | 1 |
| fold_7 | h1:fixed:0.1000:diagnostic_only | 248006 | 31372 | 1 | 0 | 1 |
| fold_7 | h3:fixed:0.0300:diagnostic_only | 247758 | 31372 | 4973 | 12 | 349 |
| fold_7 | h3:fixed:0.0500:diagnostic_only | 247758 | 31372 | 1640 | 7 | 197 |
| fold_7 | h3:fixed:0.0800:diagnostic_only | 247758 | 31372 | 430 | 1 | 74 |
| fold_7 | h3:fixed:0.1000:diagnostic_only | 247758 | 31372 | 264 | 1 | 7 |
| fold_7 | h5:fixed:0.0300:eligible | 247510 | 31372 | 8104 | 13 | 96 |
| fold_7 | h5:fixed:0.0500:eligible | 247510 | 31372 | 3308 | 7 | 232 |
| fold_7 | h5:fixed:0.0800:eligible | 247510 | 31372 | 932 | 3 | 114 |
| fold_7 | h5:fixed:0.1000:eligible | 247510 | 31372 | 545 | 1 | 40 |
| fold_7 | h10:fixed:0.0300:eligible | 246890 | 31372 | 12761 | 4 | 16 |
| fold_7 | h10:fixed:0.0500:eligible | 246890 | 31372 | 7336 | 6 | 94 |
| fold_7 | h10:fixed:0.0800:eligible | 246890 | 31372 | 2976 | 4 | 101 |
| fold_7 | h10:fixed:0.1000:eligible | 246890 | 31372 | 1677 | 3 | 72 |
| fold_7 | h20:fixed:0.0300:diagnostic_only | 245650 | 31372 | 17116 | 1 | 0 |
| fold_7 | h20:fixed:0.0500:eligible | 245650 | 31372 | 11754 | 3 | 7 |
| fold_7 | h20:fixed:0.0800:eligible | 245650 | 31372 | 6058 | 4 | 63 |
| fold_7 | h20:fixed:0.1000:eligible | 245650 | 31372 | 3774 | 4 | 64 |
| fold_8 | h1:fixed:0.0300:diagnostic_only | 279378 | 31372 | 1387 | 7 | 313 |
| fold_8 | h1:fixed:0.0500:diagnostic_only | 279378 | 31372 | 514 | 4 | 57 |
| fold_8 | h1:fixed:0.0800:diagnostic_only | 279378 | 31372 | 85 | 1 | 22 |
| fold_8 | h1:fixed:0.1000:diagnostic_only | 279378 | 31372 | 17 | 0 | 17 |
| fold_8 | h3:fixed:0.0300:diagnostic_only | 279130 | 31372 | 5518 | 16 | 301 |
| fold_8 | h3:fixed:0.0500:diagnostic_only | 279130 | 31372 | 2287 | 7 | 199 |
| fold_8 | h3:fixed:0.0800:diagnostic_only | 279130 | 31372 | 915 | 3 | 81 |
| fold_8 | h3:fixed:0.1000:diagnostic_only | 279130 | 31372 | 516 | 2 | 34 |
| fold_8 | h5:fixed:0.0300:eligible | 278882 | 31372 | 8638 | 11 | 84 |
| fold_8 | h5:fixed:0.0500:eligible | 278882 | 31372 | 4125 | 8 | 187 |
| fold_8 | h5:fixed:0.0800:eligible | 278882 | 31372 | 1768 | 3 | 124 |
| fold_8 | h5:fixed:0.1000:eligible | 278882 | 31372 | 1147 | 3 | 52 |
| fold_8 | h10:fixed:0.0300:eligible | 278262 | 31372 | 13749 | 2 | 0 |
| fold_8 | h10:fixed:0.0500:eligible | 278262 | 31372 | 8123 | 4 | 79 |
| fold_8 | h10:fixed:0.0800:eligible | 278262 | 31372 | 4020 | 4 | 126 |
| fold_8 | h10:fixed:0.1000:eligible | 278262 | 31372 | 2786 | 2 | 78 |
| fold_8 | h20:fixed:0.0300:diagnostic_only | 277022 | 31372 | 18999 | 1 | 0 |
| fold_8 | h20:fixed:0.0500:eligible | 277022 | 31372 | 13657 | 2 | 0 |
| fold_8 | h20:fixed:0.0800:eligible | 277022 | 31372 | 7788 | 5 | 44 |
| fold_8 | h20:fixed:0.1000:eligible | 277022 | 31372 | 5514 | 4 | 56 |
| fold_9 | h1:fixed:0.0300:diagnostic_only | 310750 | 31372 | 1577 | 15 | 254 |
| fold_9 | h1:fixed:0.0500:diagnostic_only | 310750 | 31372 | 416 | 3 | 118 |
| fold_9 | h1:fixed:0.0800:diagnostic_only | 310750 | 31372 | 216 | 2 | 4 |
| fold_9 | h1:fixed:0.1000:diagnostic_only | 310750 | 31372 | 117 | 2 | 0 |
| fold_9 | h3:fixed:0.0300:diagnostic_only | 310502 | 31372 | 5925 | 17 | 236 |
| fold_9 | h3:fixed:0.0500:diagnostic_only | 310502 | 31372 | 2083 | 9 | 230 |
| fold_9 | h3:fixed:0.0800:diagnostic_only | 310502 | 31372 | 613 | 4 | 74 |
| fold_9 | h3:fixed:0.1000:diagnostic_only | 310502 | 31372 | 372 | 2 | 43 |
| fold_9 | h5:fixed:0.0300:eligible | 310254 | 31372 | 9290 | 11 | 45 |
| fold_9 | h5:fixed:0.0500:eligible | 310254 | 31372 | 4053 | 10 | 184 |
| fold_9 | h5:fixed:0.0800:eligible | 310254 | 31372 | 1288 | 6 | 98 |
| fold_9 | h5:fixed:0.1000:eligible | 310254 | 31372 | 700 | 3 | 70 |
| fold_9 | h10:fixed:0.0300:eligible | 309634 | 31372 | 13973 | 2 | 0 |
| fold_9 | h10:fixed:0.0500:eligible | 309634 | 31372 | 8364 | 6 | 50 |
| fold_9 | h10:fixed:0.0800:eligible | 309634 | 31372 | 3555 | 5 | 87 |
| fold_9 | h10:fixed:0.1000:eligible | 309634 | 31372 | 1932 | 4 | 70 |
| fold_9 | h20:fixed:0.0300:diagnostic_only | 308394 | 31372 | 17271 | 1 | 0 |
| fold_9 | h20:fixed:0.0500:eligible | 308394 | 31372 | 12504 | 2 | 29 |
| fold_9 | h20:fixed:0.0800:eligible | 308394 | 31372 | 7808 | 4 | 18 |
| fold_9 | h20:fixed:0.1000:eligible | 308394 | 31372 | 5372 | 4 | 42 |
| fold_10 | h1:fixed:0.0300:diagnostic_only | 342122 | 31372 | 979 | 9 | 349 |
| fold_10 | h1:fixed:0.0500:diagnostic_only | 342122 | 31372 | 218 | 1 | 114 |
| fold_10 | h1:fixed:0.0800:diagnostic_only | 342122 | 31372 | 11 | 0 | 10 |
| fold_10 | h1:fixed:0.1000:diagnostic_only | 342122 | 31372 | 2 | 0 | 2 |
| fold_10 | h3:fixed:0.0300:diagnostic_only | 341874 | 31124 | 4157 | 11 | 283 |
| fold_10 | h3:fixed:0.0500:diagnostic_only | 341874 | 31124 | 1235 | 5 | 261 |
| fold_10 | h3:fixed:0.0800:diagnostic_only | 341874 | 31124 | 287 | 1 | 84 |
| fold_10 | h3:fixed:0.1000:diagnostic_only | 341874 | 31124 | 109 | 1 | 32 |
| fold_10 | h5:fixed:0.0300:eligible | 341626 | 30876 | 6710 | 12 | 164 |
| fold_10 | h5:fixed:0.0500:eligible | 341626 | 30876 | 2654 | 8 | 156 |
| fold_10 | h5:fixed:0.0800:eligible | 341626 | 30876 | 735 | 2 | 140 |
| fold_10 | h5:fixed:0.1000:eligible | 341626 | 30876 | 304 | 1 | 54 |
| fold_10 | h10:fixed:0.0300:eligible | 341006 | 30256 | 10423 | 5 | 44 |
| fold_10 | h10:fixed:0.0500:eligible | 341006 | 30256 | 5633 | 5 | 53 |
| fold_10 | h10:fixed:0.0800:eligible | 341006 | 30256 | 2071 | 3 | 110 |
| fold_10 | h10:fixed:0.1000:eligible | 341006 | 30256 | 1007 | 2 | 71 |
| fold_10 | h20:fixed:0.0300:diagnostic_only | 339766 | 29016 | 13047 | 2 | 6 |
| fold_10 | h20:fixed:0.0500:eligible | 339766 | 29016 | 8095 | 3 | 25 |
| fold_10 | h20:fixed:0.0800:eligible | 339766 | 29016 | 3819 | 2 | 90 |
| fold_10 | h20:fixed:0.1000:eligible | 339766 | 29016 | 2372 | 2 | 68 |

## Boundary Flags

- external_data_fetch: no
- target_definition_modified: no
- fixed_threshold_mainline_modified: no
- persistent_db_table_written: no
- full_target_matrix_committed: no
- model_training: no
- probability_calibration: no
- readiness_assigned: no
- holdout_consumed: no
- HMM_HSMM_training_modified: no
- stage03v2_implemented: no
- stage03v3_implemented: no
- trading_or_decision_output: no
