"""Development-only respiration movement gate; never a clinical apnea diagnosis."""
import math

CONTRACT_KEYS = ('method', 'frame_size', 'fs', 'window_seconds')
PERIODIC_MIN = .2
BAND_ENERGY_MIN = .4
COHERENCE_MIN = .4


def combine_decisions(decisions, ae_diagnostic, *, roi_calibrated=False, allow_development=False):
    """An AE below-threshold result cannot override missing movement evidence."""
    if type(roi_calibrated) is not bool or type(allow_development) is not bool:
        raise ValueError('보정/개발 실행 설정은 bool이어야 합니다.')
    result=dict(status='unscored',is_anomaly=None,anomaly_score=None,pred_rr_bpm=None,
                respiration_state='unassessable',movement_absence_candidate=None,clinical_apnea=None,
                experimental=True,reason=None)
    if not roi_calibrated:
        result['reason']='automatic_roi_calibration_not_validated'
    elif not allow_development:
        result['reason']='development_calibration_requires_explicit_opt_in'
    elif not decisions:
        result['reason']='no_presence_windows'
    elif any(d['respiration_state']=='no_motion_detected' for d in decisions):
        result.update(respiration_state='no_motion_detected',movement_absence_candidate=True,
                      reason='movement_absence_candidate_no_ae_bpm')
    elif any(d['respiration_state']!='motion_present' for d in decisions):
        result['reason']='presence_window_unassessable'
    elif ae_diagnostic is None or ae_diagnostic.get('status')=='unscored':
        result['reason']='waveform_extractor_unscored'
    else:
        if type(ae_diagnostic.get('is_anomaly')) is not bool:
            raise ValueError('AE is_anomaly는 bool이어야 합니다.')
        score,bpm=ae_diagnostic.get('anomaly_score'),ae_diagnostic.get('pred_rr_bpm')
        if (type(score) not in (int,float) or not math.isfinite(score) or score<0
                or type(bpm) not in (int,float) or not math.isfinite(bpm) or bpm<=0):
            raise ValueError('AE 점수/BPM이 유효하지 않습니다.')
        result.update(status='anomaly_candidate' if ae_diagnostic['is_anomaly'] else 'below_threshold',
                      is_anomaly=ae_diagnostic['is_anomaly'],anomaly_score=score,pred_rr_bpm=bpm,
                      respiration_state='motion_present',movement_absence_candidate=False,
                      reason='development_presence_and_compatible_ae')
    return result


def check_feature(feature):
    if type(feature.get('quality_ok')) is not bool:
        raise ValueError('quality_ok는 bool이어야 합니다.')
    for key in ('amplitude_px', 'periodic_concentration', 'respiratory_energy_fraction', 'spatial_coherence'):
        value = feature.get(key)
        if type(value) not in (int,float) or not math.isfinite(value) or value < 0:
            raise ValueError(f'유한한 음수 아닌 특성이 필요합니다: {key}')
    return {key: feature[key] for key in CONTRACT_KEYS}


def classify_motion(feature, calibration, *, allow_development=False):
    """Return BPM only for positive motion evidence under a compatible calibration.

    Development artifacts require an explicit opt-in from the caller. A quality
    failure is never converted to absence or a normal AE decision.
    """
    contract = check_feature(feature)
    if type(allow_development) is not bool:
        raise ValueError('개발 실행 설정은 bool이어야 합니다.')
    if any(type(calibration.get(key)) is not bool for key in ('development_usable','production_ready')):
        raise ValueError('보정 상태는 bool이어야 합니다.')
    result = dict(respiration_state='unassessable', pred_rr_bpm=None,
                  movement_absence_candidate=None, clinical_apnea=None,
                  experimental=True, reason=None)
    if not feature['quality_ok']:
        result['reason'] = ','.join(feature['quality_reasons'])
    elif not calibration.get('development_usable'):
        result['reason'] = 'calibration_not_validated'
    elif not calibration.get('production_ready') and not allow_development:
        result['reason'] = 'development_calibration_requires_explicit_opt_in'
    elif contract != calibration.get('feature_contract'):
        result['reason'] = 'feature_contract_mismatch'
    elif feature['amplitude_px'] < calibration['amplitude_threshold_px']:
        result.update(respiration_state='no_motion_detected', movement_absence_candidate=True,
                      reason='motion_below_development_threshold')
    elif (feature['periodic_concentration'] < PERIODIC_MIN
          or feature['respiratory_energy_fraction'] < BAND_ENERGY_MIN
          or feature['spatial_coherence'] < COHERENCE_MIN):
        result['reason'] = 'motion_without_sufficient_respiratory_evidence'
    elif (type(feature.get('candidate_bpm')) not in (int,float)
          or not math.isfinite(feature['candidate_bpm']) or feature['candidate_bpm'] <= 0):
        result['reason'] = 'no_supported_respiration_rate'
    else:
        result.update(respiration_state='motion_present', movement_absence_candidate=False,
                      pred_rr_bpm=feature['candidate_bpm'], reason='periodic_motion_evidence')
    return result


def fit_calibration(records):
    """Generate thresholds from train; select using reviewed positive/static valid.

    Synthetic controls and normal-assumed labels never choose the threshold. Even
    passing this tiny, development-exposed cross-camera bench cannot enable production.
    """
    if len({r['id'] for r in records}) != len(records):
        raise ValueError('중복 사례 ID')
    groups, sources, contracts = {}, {}, []
    for r in records:
        if ':' not in r['group_id'] or r['split'] not in ('train','valid','test'):
            raise ValueError('데이터셋 포함 영아/촬영 ID가 필요합니다.')
        for mapping, key in ((groups,r['group_id']), (sources,r['source_sha256'])):
            if key in mapping and mapping[key] != r['split']:
                raise ValueError('촬영/영아 분할 누수')
            mapping[key] = r['split']
    selected = [r for r in records if r['split'] in ('train','valid')
                and r['label'] in ('normal_reviewed_motion','static_simulation')]
    for r in selected:
        for f in r['windows']:
            contracts.append(check_feature(f))
    if not contracts or any(c != contracts[0] for c in contracts):
        raise ValueError('특성 계약이 다르거나 창이 없습니다.')
    result = dict(schema=2, development_usable=False, production_ready=False,
                  feature_contract=contracts[0], amplitude_threshold_px=None,
                  thresholds=dict(periodic_concentration=PERIODIC_MIN,
                                  respiratory_energy_fraction=BAND_ENERGY_MIN,
                                  spatial_coherence=COHERENCE_MIN),
                  reason=None, validation=[], validation_used_for_threshold_selection=True,
                  limitations=['no_same_camera_moving_positive_control',
                               'development_exposed_static_simulation', 'no_clinical_apnea_labels',
                               'camera_distance_and_roi_dependence'])
    normal, static = [], []
    for r in selected:
        if r['split'] == 'train':
            target = normal if r['label'] == 'normal_reviewed_motion' else static
            target.extend(f['amplitude_px'] for f in r['windows'] if f['quality_ok'])
    if not normal or not static:
        result['reason'] = 'missing_quality_train_positive_or_static'
        return result
    if min(normal) <= max(static):
        result['reason'] = 'train_motion_amplitudes_overlap'
        return result
    midpoint = float((min(normal)+max(static))/2)
    result['train_amplitude_range'] = dict(normal=[min(normal),max(normal)], static=[min(static),max(static)])
    result['development_usable'] = True
    candidates = {midpoint} | {max(static)*factor for factor in (1.25,1.5,2.,3.,5.,10.,16.)}
    candidates = sorted((t for t in candidates if max(static)<t<min(normal)),reverse=True)
    evaluations=[]
    for threshold in candidates:
        result['amplitude_threshold_px']=float(threshold)
        evaluated,valid_labels=[],set()
        for r in selected:
            if r['split'] != 'valid':
                continue
            valid_labels.add(r['label'])
            expected='motion_present' if r['label']=='normal_reviewed_motion' else 'no_motion_detected'
            decisions=[classify_motion(f,result,allow_development=True) for f in r['windows']]
            okay=bool(decisions) and all(d['respiration_state']==expected for d in decisions)
            evaluated.append(dict(id=r['id'],expected=expected,passed=okay,decisions=decisions))
        passed=(valid_labels=={'normal_reviewed_motion','static_simulation'}
                and all(r['passed'] for r in evaluated))
        evaluations.append(dict(threshold=float(threshold),passed=passed))
        if passed:
            result['validation']=evaluated
            break
    else:
        result['development_usable']=False
        result['amplitude_threshold_px']=None
        result['validation']=evaluated if candidates else []
    result['threshold_candidates']=evaluations
    result['reason']='development_threshold_selected_on_valid' if result['development_usable'] else 'validation_failed_or_missing_class'
    return result
