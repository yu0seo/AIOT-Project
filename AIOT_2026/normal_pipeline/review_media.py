"""Repair browser video previews and clearly distinguish reference/model signals."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess

import cv2


def find_ffmpeg():
    candidates=[os.environ.get('AIR400_FFMPEG'), str(Path(__file__).parent/'tools'/'ffmpeg.exe'), shutil.which('ffmpeg')]
    return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file()),None)


def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def prepare_media(clip, review):
    """Make VP8/WebM only for browser-unsupported sources. Never alter originals."""
    review=Path(review)
    media_dir=review/'media'
    media_dir.mkdir(parents=True, exist_ok=True)
    clip_id=clip['id']
    if not re.fullmatch(r'[A-Za-z0-9_]+', clip_id):
        raise ValueError('Unsafe clip ID')
    video=Path(clip['video']).resolve()
    original_hash=file_hash(video)
    if original_hash != clip['video_sha256']:
        raise ValueError(f'Source changed since scan: {clip_id}')
    receipt=media_dir/f'{clip_id}.json'
    if receipt.exists():
        cached=json.loads(receipt.read_text(encoding='utf-8'))
        if cached.get('version')==1 and cached.get('video_sha256')==original_hash and (review/cached['poster']).exists():
            preview=review/cached['src'] if cached.get('converted') else video
            if preview.is_file() and file_hash(preview)==cached['preview_sha256']:
                return cached
    cap=cv2.VideoCapture(str(video))
    writer=None
    temp=None
    try:
        if not cap.isOpened():
            raise ValueError(f'Cannot decode source: {video}')
        fps=float(cap.get(cv2.CAP_PROP_FPS))
        expected=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        codec=int(cap.get(cv2.CAP_PROP_FOURCC))
        codec=''.join(chr((codec >> 8*i)&255) for i in range(4))
        ok,frame=cap.read()
        if not ok or not math.isfinite(fps) or fps<=0:
            raise ValueError(f'No decodable source frames: {video}')
        h,w=frame.shape[:2]
        scale=min(1., 1280/w)
        width=max(2,int(w*scale)//2*2)
        height=max(2,int(h*scale)//2*2)
        poster=f'media/{clip_id}.jpg'
        if not cv2.imwrite(str(review/poster),cv2.resize(frame,(width,height))):
            raise IOError('Failed to write preview poster')
        converted=codec.lower() not in ('h264','avc1')
        if converted:
            ffmpeg=find_ffmpeg()
            if ffmpeg:
                preview=media_dir/f'{clip_id}.mp4'
                temp=media_dir/f'{clip_id}.part.mp4'
                result=subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-y','-i',str(video),
                       '-map','0:v:0','-an','-vf',f'scale={width}:{height}',
                       '-c:v','libx264','-preset','ultrafast','-crf','20','-threads','2',
                       '-pix_fmt','yuv420p','-fps_mode','passthrough','-movflags','+faststart',str(temp)],
                       capture_output=True,text=True)
                if result.returncode:
                    raise RuntimeError(f'Preview conversion failed: {result.stderr[-2000:]}')
                count=expected
            else:
                preview=media_dir/f'{clip_id}.webm'
                temp=media_dir/f'{clip_id}.part.webm'
                writer=cv2.VideoWriter(str(temp),cv2.VideoWriter_fourcc(*'VP80'),fps,(width,height))
                if not writer.isOpened():
                    raise ValueError('OpenCV VP8 encoder is unavailable')
                count=0
                while ok:
                    writer.write(cv2.resize(frame,(width,height)) if (width,height)!=(w,h) else frame)
                    count+=1
                    ok,frame=cap.read()
                writer.release()
                writer=None
                if count != expected:
                    raise ValueError(f'Decoded {count} frames but expected {expected}')
            check=cv2.VideoCapture(str(temp))
            valid=(check.isOpened() and int(check.get(cv2.CAP_PROP_FRAME_COUNT))==count
                   and abs(check.get(cv2.CAP_PROP_FPS)-fps)<.001)
            check.release()
            if not valid:
                raise ValueError('Browser preview changed frame count or FPS')
            temp.replace(preview)
            src=f'media/{preview.name}'
        else:
            preview=video
            src=video.as_uri()
        record={'version':1,'src':src,'mime':'video/webm' if preview.suffix=='.webm' else 'video/mp4',
                'poster':poster,'converted':converted,'source_codec':codec,'video_sha256':original_hash,
                'preview_sha256':file_hash(preview),'frames':expected,'fps':fps,
                'preview_width':width,'preview_height':height}
        receipt.write_text(json.dumps(record,indent=2),encoding='utf-8')
        return record
    finally:
        cap.release()
        if writer is not None:
            writer.release()


def write_page(clip, review, media, prediction=None):
    review=Path(review)
    review.mkdir(parents=True,exist_ok=True)
    esc=lambda x:html.escape(str(x),quote=True)
    clip_id=clip['id']
    if prediction and prediction.get('video_sha256')!=clip.get('video_sha256'):
        raise ValueError('Prediction does not belong to the reviewed source video')
    if prediction:
        model=f'''<p>이 영상의 {prediction['start_sec']:g}~{prediction['end_sec']:g}초를 기존 DeepPhys로 추론했습니다.
정상·비정상 승인을 뜻하지 않습니다. 위 주석과 진폭 단위가 다르며, 정답 주석의 대체물이 아닙니다.</p>
<img src="{esc(prediction['png'])}" alt="이 영상의 DeepPhys 추정 파형">'''
    else:
        model='<p>아직 이 영상의 추론 결과를 생성하지 않았습니다. 이상 탐지 학습에 사용할 입력은 DeepPhys를 실행해 얻는 추정 파형입니다.</p>'
    copy_note='브라우저 재생용 복사본입니다. 학습과 추론에는 원본 영상을 사용합니다.' if media['converted'] else ''
    page=f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(clip_id)} · 호흡 구간 검토</title>
<style>body{{max-width:1100px;margin:28px auto;padding:0 18px;font-family:system-ui,sans-serif;line-height:1.65;color:#172033}}h1{{margin-bottom:8px}}h2{{margin-top:34px;font-size:21px}}video{{width:100%;max-width:960px;max-height:65vh;background:#111}}img{{display:block;width:100%;height:auto}}.note{{padding:12px 16px;background:#eef4ff;border-radius:8px}}.error{{color:#a21b1b}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}}a{{color:#174ea6}}</style></head>
<body><p><a href="index.html">← 영상 목록</a></p><h1>{esc(clip_id)}</h1>
<p>영상을 재생하며 호흡 시점 주석과 함께 확인하세요. 정상 구간은 별도 승인해야 합니다.</p>
<video controls playsinline preload="metadata" poster="{esc(media['poster'])}"><source src="{esc(media['src'])}" type="{esc(media['mime'])}">브라우저가 이 영상을 지원하지 않습니다.</video>
<p id="video-error" class="error" hidden>영상을 불러오지 못했습니다. 이 페이지를 닫고 최신 검토 목록에서 다시 열어 주세요.</p>
<p>영상 시간: <output id="clock">0.00</output>초 / {clip['duration']:.2f}초</p><p>{copy_note}</p>
<h2>1. 호흡 시점 주석 · 사람이 표시한 정답</h2>
<p class="note">뾰족한 봉우리는 사람이 표시한 호흡 시점을 가우시안 형태로 펼친 주석입니다.
센서로 측정한 호흡량이나 DeepPhys 추론 결과가 아닙니다.</p>
<img src="{esc(clip_id)}.png" alt="호흡 시점의 정답 주석">
<h2>2. DeepPhys 추정 파형 · 이상 탐지 학습에 사용할 신호</h2>{model}
<p>정답 주석의 시간축과 영상의 실제 정렬을 확인한 뒤 정상 구간·영상 품질을 승인하세요.</p>
<details><summary>파일 및 시간축 정보</summary><pre>{esc(json.dumps(clip,ensure_ascii=False,indent=2))}</pre></details>
<script>const video=document.querySelector('video');video.addEventListener('timeupdate',()=>document.querySelector('#clock').value=video.currentTime.toFixed(2));video.addEventListener('error',()=>document.querySelector('#video-error').hidden=false);video.querySelector('source').addEventListener('error',()=>document.querySelector('#video-error').hidden=false);</script></body></html>'''
    (review/f'{clip_id}.html').write_text(page,encoding='utf-8')


def repair(workdir,workers=2):
    """Refresh presentation only, preserving all manifests and human approvals."""
    workdir=Path(workdir)
    manifest_path=workdir/'manifest.json'
    approvals_path=workdir/'approvals.json'
    snapshots={p:file_hash(p) for p in (manifest_path,approvals_path)}
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    clips=[c for c in manifest['clips'] if c['status']=='pending_review']
    review=workdir/'review'
    registry_path=review/'predictions.json'
    registry=json.loads(registry_path.read_text(encoding='utf-8')) if registry_path.exists() else {}
    errors=[]
    converted=0
    with ThreadPoolExecutor(max_workers=max(1,min(4,workers))) as pool:
        futures={pool.submit(prepare_media,c,review):c for c in clips}
        for i,future in enumerate(as_completed(futures),1):
            clip=futures[future]
            try:
                media=future.result()
                write_page(clip,review,media,registry.get(clip['id']))
                converted+=int(media['converted'])
            except Exception as e:
                errors.append({'clip':clip['id'],'error':str(e)})
            if i%20==0 or i==len(clips):
                print(f'Browser review {i}/{len(clips)}, errors={len(errors)}',flush=True)
    for path,before in snapshots.items():
        if file_hash(path)!=before:
            raise RuntimeError(f'Review metadata changed during refresh: {path}')
    report={'pages':len(clips)-len(errors),'converted_previews':converted,'errors':errors,
            'manifest_sha256':snapshots[manifest_path],'approvals_sha256':snapshots[approvals_path]}
    (review/'media_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    if errors:
        raise RuntimeError('Some previews failed; see review/media_report.json')
    return report


def predict_for_review(args):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from inference_adapter import AirExtractor
    from pipeline import receipt_signature, save_json, save_prediction
    workdir=args.workdir.resolve()
    clips=json.loads((workdir/'manifest.json').read_text(encoding='utf-8'))['clips']
    clip=next((c for c in clips if c['id']==args.clip and c['status']=='pending_review'),None)
    if clip is None:
        raise ValueError('Unknown or excluded clip')
    if file_hash(clip['video'])!=clip['video_sha256']:
        raise ValueError('Video changed since scan')
    extractor=AirExtractor(args.repo,args.config,args.checkpoint)
    pred=extractor.predict_video(clip['video'],args.start)
    directory=workdir/'review'/'predictions'
    directory.mkdir(parents=True,exist_ok=True)
    base=f"{clip['id']}_{args.start:g}"
    path=directory/f'{base}.hdf5'
    save_prediction(path,pred,{'video_sha256':clip['video_sha256'],'clip_id':clip['id'],
                              'start_sec':args.start,'extractor_signature':receipt_signature(extractor.receipt)})
    save_json(directory/f'{base}_extractor.json',extractor.receipt)
    fig,ax=plt.subplots(figsize=(12,3.5))
    ax.plot(pred['time_sec']+args.start,pred['respiration'],linewidth=1.1)
    ax.set(xlabel='Video time (seconds)',ylabel='DeepPhys prediction (a.u.)',
           title=f"{clip['id']}: DeepPhys prediction, {args.start:g}-{args.start+30:g}s")
    ax.grid(alpha=.25)
    fig.tight_layout()
    png=directory/f'{base}.png'
    fig.savefig(png,dpi=150)
    plt.close(fig)
    registry_path=workdir/'review'/'predictions.json'
    registry=json.loads(registry_path.read_text(encoding='utf-8')) if registry_path.exists() else {}
    registry[clip['id']]={'png':f'predictions/{png.name}','hdf5':f'predictions/{path.name}',
                           'start_sec':args.start,'end_sec':args.start+30,'video_sha256':clip['video_sha256']}
    save_json(registry_path,registry)
    media=prepare_media(clip,workdir/'review')
    write_page(clip,workdir/'review',media,registry[clip['id']])
    print(f'Added same-video model prediction: {clip["id"]}; normal label not assigned.',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    command=sub.add_parser('repair')
    command.add_argument('--workdir',type=Path,required=True)
    command.add_argument('--workers',type=int,default=2)
    command=sub.add_parser('predict')
    command.add_argument('--workdir',type=Path,required=True)
    command.add_argument('--clip',required=True)
    command.add_argument('--start',type=float,default=0)
    command.add_argument('--repo',type=Path,required=True)
    command.add_argument('--config',type=Path,required=True)
    command.add_argument('--checkpoint',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='repair':
        print(json.dumps(repair(args.workdir,args.workers),indent=2),flush=True)
    else:
        predict_for_review(args)


if __name__=='__main__':
    main()
