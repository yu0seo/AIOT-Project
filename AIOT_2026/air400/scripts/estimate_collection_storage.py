"""Read only public directory indexes and HTTP HEAD headers; never download videos."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import html
import json
import re
import ssl
import time
import urllib.parse
import urllib.request

from air400_paths import DATA, PROJECT

BASE="https://coe.northeastern.edu/Research/AClab/AIR-400/"
OUT=PROJECT/"06_단일클래스_학습데이터/configs/storage_estimate.json"


def request(url,method):
    assert url.startswith(BASE)
    context=ssl._create_unverified_context()  # Existing public-host TLS proxy exception.
    for attempt in range(3):
        try:
            req=urllib.request.Request(url,method=method,headers={"User-Agent":"AIOT-metadata-size-check/1.0"})
            with urllib.request.urlopen(req,context=context,timeout=20) as response:
                headers=dict(response.headers.items())
                # A GET is used only for directory index HTML, never for an MP4.
                if method=="GET":
                    assert url.endswith("/")
                    return response.read().decode("utf-8")
                return headers
        except Exception:
            if attempt==2:raise
            time.sleep(1)


def subject(number):
    folder=f"S{number:02d}";url=BASE+folder+"/"
    page=request(url,"GET")
    names=[urllib.parse.unquote(html.unescape(s)) for s in re.findall(r'href="([^"]+)"',page)]
    return [{"folder":folder,"name":s,"url":url+s,"relative_path":f"videos/{folder}/{s}"}
            for s in names if re.fullmatch(r"\d+\.mp4",s)]


def head(record):
    try:
        headers=request(record["url"],"HEAD")
        header={k.lower():v for k,v in headers.items()}
        size=int(header["content-length"]) if "content-length" in header else None
        local=DATA/record["relative_path"]
        existing=local.is_file() and size is not None and local.stat().st_size==size
        return {**record,"content_length_bytes":size,"last_modified":header.get("last-modified"),
                "existing_local_file_size_matches":existing,"local_size_bytes":local.stat().st_size if local.is_file() else 0}
    except Exception as error:
        return {**record,"content_length_bytes":None,"error":str(error)}


def main():
    started=time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as pool:
        records=[r for group in pool.map(subject,range(1,11)) for r in group]
    results=[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures=[pool.submit(head,r) for r in records]
        for future in as_completed(futures):
            results.append(future.result())
            if len(results)%50==0:print(f"Read metadata {len(results)}/{len(records)}",flush=True)
    results.sort(key=lambda r:(r["folder"],int(r["name"][:-4])))
    known=[r for r in results if r["content_length_bytes"] is not None]
    present=[r for r in known if r.get("existing_local_file_size_matches")]
    total=sum(r["content_length_bytes"] for r in known)
    present_bytes=sum(r["content_length_bytes"] for r in present)
    folders=[]
    for number in range(1,11):
        folder=f"S{number:02d}";group=[r for r in known if r["folder"]==folder]
        folders.append({"folder":folder,"count":len(group),"bytes":sum(r["content_length_bytes"] for r in group)})
    summary={"checked_at":datetime.now().astimezone().isoformat(),"scope":"Only S01-S10 folder-level numeric MP4 short clips",
        "request_methods":"10 directory GETs and video HEAD only; no video bodies requested", "video_body_bytes_downloaded":0,
        "video_count":len(results),"known_exact_size_count":len(known),"unknown_size_count":len(results)-len(known),
        "all_sizes_known":len(results)==len(known),"total_video_bytes":total,"total_video_GB_decimal":total/1e9,"total_video_GiB":total/(1024**3),
        "already_local_size_matched_count":len(present),"already_local_size_matched_bytes":present_bytes,
        "additional_video_count":len(results)-len(present),"additional_video_bytes":total-present_bytes,
        "additional_video_GB_decimal":(total-present_bytes)/1e9,"additional_video_GiB":(total-present_bytes)/(1024**3),
        "folders":folders,"elapsed_sec":time.perf_counter()-started,"files":results,
        "not_included":["original_videos long recordings","AIR_125 archive","root duplicate demo","weights/environments","new HDF5 and preview videos"]}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in summary.items() if k!="files"},ensure_ascii=False,indent=2),flush=True)


if __name__=="__main__":main()
