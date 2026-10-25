"""Trusted fixed-step launcher already bound to an outer Windows Job Object."""
import json,os,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.training_command import validate_request,CommandError

def main(path):
    with Path(path).open('rb') as reader:raw=reader.read(65537)
    if len(raw)>65536:raise CommandError('request_too_large')
    data=json.loads(raw);command=validate_request(data,path)
    environment=os.environ.copy();environment.update(data['environment'])
    if data['path_prefix']:environment['PATH']=os.pathsep.join(data['path_prefix']+[environment.get('PATH','')])
    # O_CREAT deliberately absent: only the previously owned log may be opened.
    with os.fdopen(os.open(data['log'],os.O_WRONLY|os.O_APPEND),'wb') as log:
        log.write(('STEP: '+data['step']+'\n').encode('utf8'));log.flush()
        process=subprocess.Popen(command,cwd=data['upstream'],env=environment,stdout=log,stderr=subprocess.STDOUT,shell=False)
        code=process.wait();log.write(('EXIT: '+str(code)+'\n').encode('utf8'))
        return code

if __name__=='__main__':
    try:raise SystemExit(main(sys.argv[1]))
    except (OSError,ValueError,CommandError):raise SystemExit(120)
