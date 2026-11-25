"""Build an isolated Windows Coarse2Fine extension; keep pyflow sources/env intact."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from normal_pipeline.no_motion import sha256


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--cython-dir',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    source,output,dependency=a.source.resolve(),a.output.resolve(),a.cython_dir.resolve()
    if sys.platform!='win32' or output.exists():
        p.error('Windows에서 새 --output 폴더를 지정하세요.')
    if not (source/'pyflow.pyx').is_file() or not (dependency/'Cython').is_dir():
        p.error('pyflow 원본 및 별도 Cython 설치 폴더가 필요합니다.')
    original={str(f.relative_to(source)):sha256(f) for f in [source/'pyflow.pyx',*sorted((source/'src').glob('*'))] if f.is_file()}
    output.mkdir(parents=True,exist_ok=False)
    shutil.copytree(source/'src',output/'src')
    shutil.copy2(source/'pyflow.pyx',output/'pyflow.pyx')
    project=output/'src/project.h'
    contents=project.read_text()
    if '\n#define _LINUX_MAC\n' not in contents:
        p.error('예상한 pyflow project.h가 아닙니다. 원본을 확인하세요.')
    project.write_text(contents.replace('\n#define _LINUX_MAC\n','\n// Windows MSVC: _LINUX_MAC disabled\n'))
    # Upstream explicitly instructs disabling this macro for Visual Studio. No
    # numerical algorithm change; retain the original sources and their license.
    script="""import sys
from pathlib import Path
sys.path.insert(0, DEPENDENCY)
from setuptools import setup, Extension
from Cython.Build import cythonize
import numpy
sources=['pyflow.pyx']+[str(p) for p in Path('src').glob('*.cpp') if p.name!='Coarse2FineFlowWrapper.cpp']
# The pyx distutils directive already adds Coarse2FineFlowWrapper.cpp.
setup(name='air400-pyflow-bench',ext_modules=cythonize([Extension('pyflow',sources,include_dirs=[numpy.get_include()],language='c++')],compiler_directives={'language_level':3}),script_args=['build_ext','--inplace'])
""".replace('DEPENDENCY',repr(str(dependency)))
    (output/'build_native.py').write_text(script,encoding='utf-8')
    with (output/'build.log').open('w',encoding='utf-8') as log:
        result=subprocess.run([sys.executable,'-B','build_native.py'],cwd=output,stdout=log,stderr=subprocess.STDOUT)
    binaries=list(output.glob('pyflow*.pyd'))
    unchanged=all(sha256(source/f)==digest for f,digest in original.items())
    report=dict(python=sys.version,source=str(source),source_hashes=original,
                patch='Disable _LINUX_MAC in copied project.h, as directed by upstream for Visual Studio.',
                success=result.returncode==0 and len(binaries)==1,source_unchanged=unchanged,
                binaries={f.name:sha256(f) for f in binaries})
    (output/'build.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(success=report['success'],source_unchanged=unchanged,output=str(output))))
    if not report['success'] or not unchanged:
        p.exit(1,'빌드 실패: 출력 폴더의 build.log/build.json을 확인하세요.\n')


if __name__=='__main__':
    main()
