# Stage03V RERUN1 Downshift Experiment

- index_id: STAGE03V-RERUN1-v1
- status: pass
- source_db_path: data/db/a_share_hmm_tushare_v7.duckdb
- fold_plan_path: reports/stage03v/purge_embargo_fold_plan_v2.json
- validation_entity_day_count: 5021776
- candidate_slice_count: 32
- prospective_holdout_rows_evaluated: 0
- trial_accounting_invalidation_recorded: yes

## Primary Model Minus Baseline Deltas

| slice_id | metric | delta | ci_low | ci_high | ci_status |
|---|---|---:|---:|---:|---|
| close_t:h5:fixed:0.0300:eligible:isotonic_calibration | max_drawdown | -0.03202593994231717 | -0.08994161033104527 | 0.026540922514828612 | pass |
| close_t:h5:fixed:0.0300:eligible:isotonic_calibration | cvar_95 | -0.001325765933514217 | -0.002867890825502266 | 0.0002524982659541116 | pass |
| close_t:h5:fixed:0.0300:eligible:isotonic_calibration | realized_volatility | -0.0002339494464368378 | -0.0007104746823763961 | 0.00031328889873096985 | pass |
| close_t:h5:fixed:0.0300:eligible:platt_logistic_calibration | max_drawdown | -0.03682684931629443 | -0.06645419058844294 | 0.022093280336272593 | pass |
| close_t:h5:fixed:0.0300:eligible:platt_logistic_calibration | cvar_95 | -0.001132172091925912 | -0.0026129800036950785 | 0.00019180298253821187 | pass |
| close_t:h5:fixed:0.0300:eligible:platt_logistic_calibration | realized_volatility | -6.721748222466087e-05 | -0.0004924687525947067 | 0.00048714215898771083 | pass |
| close_t:h5:fixed:0.0500:eligible:isotonic_calibration | max_drawdown | 0.041014354076353676 | -0.09859923587652575 | 0.0481543087323726 | pass |
| close_t:h5:fixed:0.0500:eligible:isotonic_calibration | cvar_95 | 0.0009289899167412505 | -0.0011177072629429887 | 0.0031486987606047967 | pass |
| close_t:h5:fixed:0.0500:eligible:isotonic_calibration | realized_volatility | 0.0008162351147653398 | 0.00015691055287184882 | 0.0016559574960111627 | pass |
| close_t:h5:fixed:0.0500:eligible:platt_logistic_calibration | max_drawdown | 0.0338345423078561 | -0.09639264230813283 | 0.03475250898083481 | pass |
| close_t:h5:fixed:0.0500:eligible:platt_logistic_calibration | cvar_95 | 0.000427439035389679 | -0.0011309401929748674 | 0.0020001903255589385 | pass |
| close_t:h5:fixed:0.0500:eligible:platt_logistic_calibration | realized_volatility | 0.0007442598883362992 | 0.00010061302949682921 | 0.001451131245956397 | pass |
| close_t:h5:fixed:0.0800:eligible:isotonic_calibration | max_drawdown | 0.03863158239945785 | -0.10705526092568561 | 0.04589444279501163 | pass |
| close_t:h5:fixed:0.0800:eligible:isotonic_calibration | cvar_95 | 0.0008792752947001659 | -0.0007685578269057107 | 0.0024616693278209255 | pass |
| close_t:h5:fixed:0.0800:eligible:isotonic_calibration | realized_volatility | 0.0007797402024262139 | 0.00013927504864518297 | 0.001723915865500561 | pass |
| close_t:h5:fixed:0.0800:eligible:platt_logistic_calibration | max_drawdown | 0.04379693061326928 | -0.1055029317777124 | 0.052408221529869146 | pass |
| close_t:h5:fixed:0.0800:eligible:platt_logistic_calibration | cvar_95 | 0.0009495491973255873 | -0.0009158860038086758 | 0.0033978903735471734 | pass |
| close_t:h5:fixed:0.0800:eligible:platt_logistic_calibration | realized_volatility | 0.001002367137405473 | 0.00033888002477397395 | 0.0019259810187820926 | pass |
| close_t:h5:fixed:0.1000:eligible:isotonic_calibration | max_drawdown | 0.03656178507813879 | -0.08901605427203936 | 0.044170035733562575 | pass |
| close_t:h5:fixed:0.1000:eligible:isotonic_calibration | cvar_95 | 0.0010125142978038223 | -0.0008199939224354426 | 0.002861884830950627 | pass |
| close_t:h5:fixed:0.1000:eligible:isotonic_calibration | realized_volatility | 0.0008519673500817608 | 0.00019013665709296528 | 0.0015952391600303109 | pass |
| close_t:h5:fixed:0.1000:eligible:platt_logistic_calibration | max_drawdown | 0.04724033269110073 | -0.10512546381073291 | 0.047398235210895104 | pass |
| close_t:h5:fixed:0.1000:eligible:platt_logistic_calibration | cvar_95 | 0.0011673261237350047 | -0.0007858705643063224 | 0.003189423649184544 | pass |
| close_t:h5:fixed:0.1000:eligible:platt_logistic_calibration | realized_volatility | 0.001135511761517648 | 0.0004059942214787417 | 0.0020169820134265056 | pass |
| close_t:h10:fixed:0.0500:eligible:isotonic_calibration | max_drawdown | 0.027653989917772237 | -0.1257114321230676 | 0.030326624132080596 | pass |
| close_t:h10:fixed:0.0500:eligible:isotonic_calibration | cvar_95 | 1.2199889544622922e-05 | -0.001589865955109496 | 0.0015242437186564215 | pass |
| close_t:h10:fixed:0.0500:eligible:isotonic_calibration | realized_volatility | 0.0005978170794912144 | -3.7904925040098396e-05 | 0.0015006275023988311 | pass |
| close_t:h10:fixed:0.0500:eligible:platt_logistic_calibration | max_drawdown | 0.026692942930025998 | -0.1019149256301525 | 0.029854605594027195 | pass |
| close_t:h10:fixed:0.0500:eligible:platt_logistic_calibration | cvar_95 | 0.0004571714734010329 | -0.0011369695049828735 | 0.002041050228074334 | pass |
| close_t:h10:fixed:0.0500:eligible:platt_logistic_calibration | realized_volatility | 0.0007906994319645047 | 0.0001370396421213588 | 0.001665451700083963 | pass |
| close_t:h10:fixed:0.0800:eligible:isotonic_calibration | max_drawdown | 0.041867719607149856 | -0.09785236737914153 | 0.04581735416266924 | pass |
| close_t:h10:fixed:0.0800:eligible:isotonic_calibration | cvar_95 | 0.001245959869840739 | -0.0005815510710277339 | 0.00296400434330052 | pass |
| close_t:h10:fixed:0.0800:eligible:isotonic_calibration | realized_volatility | 0.0009610003029121676 | 0.0002944294097047167 | 0.0019093430201614268 | pass |
| close_t:h10:fixed:0.0800:eligible:platt_logistic_calibration | max_drawdown | 0.04145211695925177 | -0.08960786729635573 | 0.0505817192531792 | pass |
| close_t:h10:fixed:0.0800:eligible:platt_logistic_calibration | cvar_95 | 0.0016932157174905302 | -0.0003888454516991051 | 0.0035667068177250997 | pass |
| close_t:h10:fixed:0.0800:eligible:platt_logistic_calibration | realized_volatility | 0.0011265113204387434 | 0.00037822684025061546 | 0.0019509573711287546 | pass |
| close_t:h10:fixed:0.1000:eligible:platt_logistic_calibration | max_drawdown | 0.047206324940976985 | -0.09618302971314781 | 0.06407613989496438 | pass |
| close_t:h10:fixed:0.1000:eligible:platt_logistic_calibration | cvar_95 | 0.0017136230385301904 | -0.0001076388363498627 | 0.0036115350200947418 | pass |
| close_t:h10:fixed:0.1000:eligible:platt_logistic_calibration | realized_volatility | 0.0011581585613851253 | 0.0004484227113382683 | 0.0021602744002635834 | pass |
| close_t:h10:fixed:0.1000:eligible:isotonic_calibration | max_drawdown | 0.04079010383508286 | -0.09516856869604612 | 0.04616209200779057 | pass |
| close_t:h10:fixed:0.1000:eligible:isotonic_calibration | cvar_95 | 0.0012451405798074716 | -0.0003646691074893687 | 0.0032830852021974145 | pass |
| close_t:h10:fixed:0.1000:eligible:isotonic_calibration | realized_volatility | 0.0009079266986898229 | 0.0002596604931809464 | 0.0017608728766356579 | pass |
| close_t:h20:fixed:0.1000:eligible:isotonic_calibration | max_drawdown | 0.011723344475519926 | -0.07196973517030625 | 0.05764680187077239 | pass |
| close_t:h20:fixed:0.1000:eligible:isotonic_calibration | cvar_95 | 0.0009354676351355992 | -0.0008276380454399573 | 0.002710219147517476 | pass |
| close_t:h20:fixed:0.1000:eligible:isotonic_calibration | realized_volatility | 0.000567277021256956 | 0.00011735362185608607 | 0.0011337617683394347 | pass |
| close_t:h20:fixed:0.1000:eligible:platt_logistic_calibration | max_drawdown | 0.00949761137156624 | -0.05407193256231644 | 0.06336829493180167 | pass |
| close_t:h20:fixed:0.1000:eligible:platt_logistic_calibration | cvar_95 | 0.0011989191647682335 | -0.00037674428070634704 | 0.0031373561603576594 | pass |
| close_t:h20:fixed:0.1000:eligible:platt_logistic_calibration | realized_volatility | 0.0006190484475420144 | 0.000166459529701811 | 0.0010914214187066353 | pass |
| close_t_minus_1:h5:fixed:0.0300:eligible:isotonic_calibration | max_drawdown | -0.019578068422369088 | -0.07408467343109858 | 0.0389960063958075 | pass |
| close_t_minus_1:h5:fixed:0.0300:eligible:isotonic_calibration | cvar_95 | -0.0010641069729627611 | -0.002590727674360666 | 0.00011484564184746248 | pass |
| close_t_minus_1:h5:fixed:0.0300:eligible:isotonic_calibration | realized_volatility | -0.0002100830992717833 | -0.000700221385235694 | 0.00041885858754108483 | pass |
| close_t_minus_1:h5:fixed:0.0300:eligible:platt_logistic_calibration | max_drawdown | -0.012081563487906899 | -0.05808945768426937 | 0.026356220108550293 | pass |
| close_t_minus_1:h5:fixed:0.0300:eligible:platt_logistic_calibration | cvar_95 | -0.0005540927449720276 | -0.0018170217484508862 | 0.0009014691572976658 | pass |
| close_t_minus_1:h5:fixed:0.0300:eligible:platt_logistic_calibration | realized_volatility | 4.645266668655036e-05 | -0.0003570277670534073 | 0.0005425175262286052 | pass |
| close_t_minus_1:h5:fixed:0.0500:eligible:isotonic_calibration | max_drawdown | 0.043456034954449496 | -0.10666524082731074 | 0.045212637410499315 | pass |
| close_t_minus_1:h5:fixed:0.0500:eligible:isotonic_calibration | cvar_95 | 0.00092055873207713 | -0.0009033302548921462 | 0.0022874529038835003 | pass |
| close_t_minus_1:h5:fixed:0.0500:eligible:isotonic_calibration | realized_volatility | 0.0007728476299549304 | 0.00014840489659641371 | 0.0016536947716289626 | pass |
| close_t_minus_1:h5:fixed:0.0500:eligible:platt_logistic_calibration | max_drawdown | 0.043868891031534685 | -0.10906931205005493 | 0.034043004362498526 | pass |
| close_t_minus_1:h5:fixed:0.0500:eligible:platt_logistic_calibration | cvar_95 | 0.0006125051154939679 | -0.0009459029817651369 | 0.0023567745994355037 | pass |
| close_t_minus_1:h5:fixed:0.0500:eligible:platt_logistic_calibration | realized_volatility | 0.0007800873865173447 | 0.00011065920821337005 | 0.0016318824397123907 | pass |
| close_t_minus_1:h5:fixed:0.0800:eligible:isotonic_calibration | max_drawdown | 0.04608471535990499 | -0.09804351271559154 | 0.03993552457361192 | pass |
| close_t_minus_1:h5:fixed:0.0800:eligible:isotonic_calibration | cvar_95 | 0.0011476550943782318 | -0.0008076944686130475 | 0.0031441401165012385 | pass |
| close_t_minus_1:h5:fixed:0.0800:eligible:isotonic_calibration | realized_volatility | 0.0008709611586484034 | 0.00018809993997557698 | 0.0016492843129184487 | pass |
| close_t_minus_1:h5:fixed:0.0800:eligible:platt_logistic_calibration | max_drawdown | 0.047008705480985236 | -0.10069587163581523 | 0.04284545181208939 | pass |
| close_t_minus_1:h5:fixed:0.0800:eligible:platt_logistic_calibration | cvar_95 | 0.0009629076635810849 | -0.001180808456427236 | 0.0030702455078487293 | pass |
| close_t_minus_1:h5:fixed:0.0800:eligible:platt_logistic_calibration | realized_volatility | 0.001003915324867856 | 0.0003455476036534245 | 0.0018596005920500694 | pass |
| close_t_minus_1:h5:fixed:0.1000:eligible:isotonic_calibration | max_drawdown | 0.04589758498479024 | -0.09641332795446594 | 0.05443205197986637 | pass |
| close_t_minus_1:h5:fixed:0.1000:eligible:isotonic_calibration | cvar_95 | 0.0011662484152839894 | -0.0006696738308850595 | 0.0029716273203483404 | pass |
| close_t_minus_1:h5:fixed:0.1000:eligible:isotonic_calibration | realized_volatility | 0.0006457005443878359 | 0.0002093537285695749 | 0.0011443729926551962 | pass |
| close_t_minus_1:h5:fixed:0.1000:eligible:platt_logistic_calibration | max_drawdown | 0.04800453510866476 | -0.09016081016104482 | 0.048943714368128215 | pass |
| close_t_minus_1:h5:fixed:0.1000:eligible:platt_logistic_calibration | cvar_95 | 0.0011525594818560456 | -0.0009056290230272909 | 0.0032900213134537146 | pass |
| close_t_minus_1:h5:fixed:0.1000:eligible:platt_logistic_calibration | realized_volatility | 0.0011607236384918052 | 0.00047712607919619965 | 0.001999600667972836 | pass |
| close_t_minus_1:h10:fixed:0.0500:eligible:isotonic_calibration | max_drawdown | 0.04379336319323934 | -0.08530046086942891 | 0.03806799085976634 | pass |
| close_t_minus_1:h10:fixed:0.0500:eligible:isotonic_calibration | cvar_95 | 0.0002908557441037886 | -0.0017618985754544445 | 0.002299362127851379 | pass |
| close_t_minus_1:h10:fixed:0.0500:eligible:isotonic_calibration | realized_volatility | 0.0005702164657334207 | -0.00011007773510124177 | 0.001546024693903504 | pass |
| close_t_minus_1:h10:fixed:0.0500:eligible:platt_logistic_calibration | max_drawdown | 0.04464688653367366 | -0.07827175203393669 | 0.05465397061912461 | pass |
| close_t_minus_1:h10:fixed:0.0500:eligible:platt_logistic_calibration | cvar_95 | 0.0010515913026728912 | -0.0008925754446954967 | 0.0027262935377332527 | pass |
| close_t_minus_1:h10:fixed:0.0500:eligible:platt_logistic_calibration | realized_volatility | 0.0008425303224040212 | 0.000168245423363265 | 0.0015759614784801703 | pass |
| close_t_minus_1:h10:fixed:0.0800:eligible:isotonic_calibration | max_drawdown | 0.05249728336840698 | -0.07399176717418633 | 0.07121832948627328 | pass |
| close_t_minus_1:h10:fixed:0.0800:eligible:isotonic_calibration | cvar_95 | 0.0013465310390344473 | -0.000438580366887994 | 0.0033599349510364013 | pass |
| close_t_minus_1:h10:fixed:0.0800:eligible:isotonic_calibration | realized_volatility | 0.0009148653638388158 | 0.0003186815988158742 | 0.00191214610292717 | pass |
| close_t_minus_1:h10:fixed:0.0800:eligible:platt_logistic_calibration | max_drawdown | 0.052161162826898644 | -0.10020763247147661 | 0.05594570309852845 | pass |
| close_t_minus_1:h10:fixed:0.0800:eligible:platt_logistic_calibration | cvar_95 | 0.0017820937926191702 | -4.0641617525911766e-05 | 0.0037269767968045836 | pass |
| close_t_minus_1:h10:fixed:0.0800:eligible:platt_logistic_calibration | realized_volatility | 0.0010788484555365758 | 0.0003783847362719839 | 0.0019353298182720685 | pass |
| close_t_minus_1:h10:fixed:0.1000:eligible:isotonic_calibration | max_drawdown | 0.05206526953727353 | -0.08355095374599844 | 0.05933209153667389 | pass |
| close_t_minus_1:h10:fixed:0.1000:eligible:isotonic_calibration | cvar_95 | 0.0014018765098898767 | -0.0002475069658250154 | 0.0030811419213778004 | pass |
| close_t_minus_1:h10:fixed:0.1000:eligible:isotonic_calibration | realized_volatility | 0.0009072480821212554 | 0.00016222593350494714 | 0.0017050146395052746 | pass |
| close_t_minus_1:h10:fixed:0.1000:eligible:platt_logistic_calibration | max_drawdown | 0.05431692698696289 | -0.09329922405979432 | 0.05264497783058912 | pass |
| close_t_minus_1:h10:fixed:0.1000:eligible:platt_logistic_calibration | cvar_95 | 0.0015630731346663665 | -0.00043676504125222444 | 0.003604029413865096 | pass |
| close_t_minus_1:h10:fixed:0.1000:eligible:platt_logistic_calibration | realized_volatility | 0.0010994951713075088 | 0.00036929386979324717 | 0.0019390375506446913 | pass |
| close_t_minus_1:h20:fixed:0.1000:eligible:isotonic_calibration | max_drawdown | 0.01183504899642751 | -0.06208209030078141 | 0.05225626853652502 | pass |
| close_t_minus_1:h20:fixed:0.1000:eligible:isotonic_calibration | cvar_95 | 0.0009245580595068081 | -0.000904023197970619 | 0.00285888010743743 | pass |
| close_t_minus_1:h20:fixed:0.1000:eligible:isotonic_calibration | realized_volatility | 0.0005579553740604048 | 4.824822821078283e-05 | 0.0011096192835785914 | pass |
| close_t_minus_1:h20:fixed:0.1000:eligible:platt_logistic_calibration | max_drawdown | 0.010378315914392311 | -0.05416870479501192 | 0.06900285967096483 | pass |
| close_t_minus_1:h20:fixed:0.1000:eligible:platt_logistic_calibration | cvar_95 | 0.0010854988404421922 | -0.000600752446664652 | 0.0028601542640425068 | pass |
| close_t_minus_1:h20:fixed:0.1000:eligible:platt_logistic_calibration | realized_volatility | 0.0005908960630981661 | 0.00019214292836297752 | 0.001157389656408961 | pass |

## Boundary Flags

- external_data_fetch: no
- target_definition_modified: no
- fixed_threshold_mainline_modified: no
- persistent_db_table_written: no
- full_target_matrix_committed: no
- full_score_matrix_committed: no
- model_family_changed: no
- readiness_threshold_tuned: no
- ordinal_bucket_tuned_after_first_run: no
- exposure_rule_tuned_after_first_run: no
- holdout_consumed: no
- HMM_HSMM_training_modified: no
- stage03v2_implemented: no
- stage03v3_implemented: no
- trading_or_decision_output: no
- research_only_simulation: yes

## Blocking Reasons

- none
