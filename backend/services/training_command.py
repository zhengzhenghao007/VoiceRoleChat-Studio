"""Owned Windows training commands; no arbitrary API execution or PID takeover."""
import json,os,re,sys,time
from pathlib import Path
from threading import RLock
from uuid import uuid4
from services.owned_worker import OwnedWorker,OwnershipError

STEPS={'text':'GPT_SoVITS/prepare_datasets/1-get-text.py','hubert':'GPT_SoVITS/prepare_datasets/2-get-hubert-wav32k.py','speaker':'GPT_SoVITS/prepare_datasets/2-get-sv.py','semantic':'GPT_SoVITS/prepare_datasets/3-get-semantic.py','sovits':'GPT_SoVITS/s2_train.py','gpt':'GPT_SoVITS/s1_train.py'}
ENV={'PYTHONIOENCODING','PYTHONUTF8','inp_text','inp_wav_dir','exp_name','opt_dir','i_part','all_parts','_CUDA_VISIBLE_DEVICES','is_half','version','bert_pretrained_dir','cnhubert_base_dir','sv_path','pretrained_s2G','s2config_path','hz'}
PATH_ENV={'inp_text','inp_wav_dir','opt_dir','bert_pretrained_dir','cnhubert_base_dir','sv_path','pretrained_s2G','s2config_path'}
class CommandError(RuntimeError):
    def __init__(self,code):self.code=code;super().__init__('Training command: '+code)

def canonical(path):
    try:
        path=Path(path).absolute()
        if path.resolve()!=path:raise ValueError('Noncanonical path')
        return path
    except (OSError,RuntimeError,ValueError) as error:raise CommandError('unsafe_path') from error

def validate_request(data,request_path=None):
    if not isinstance(data,dict) or set(data)!={'version','step','python','upstream','jobs','log','environment','path_prefix'} or type(data['version']) is not int or data['version']!=1:raise CommandError('invalid_request')
    if data['step'] not in STEPS:raise CommandError('invalid_step')
    for key in ('python','upstream','jobs','log'):
        if not isinstance(data[key],str) or len(data[key])>32767 or '\0' in data[key]:raise CommandError('invalid_path')
    upstream=canonical(data['upstream']);jobs=canonical(data['jobs']);log=canonical(data['log']);python=canonical(data['python'])
    if not python.is_file() or not upstream.is_dir() or log.parent!=jobs or not re.fullmatch(r'[0-9a-f]{32}\.log',log.name) or not log.is_file():raise CommandError('invalid_destination')
    if request_path is not None:
        path=canonical(request_path)
        if path.name!='request.json' or not re.fullmatch(r'[0-9a-f]{32}',path.parent.name) or path.parent.parent!=canonical(jobs/'.commands'):raise CommandError('invalid_request_path')
    variables=data['environment'];prefix=data['path_prefix']
    if not isinstance(variables,dict) or not set(variables)<=ENV or not isinstance(prefix,list) or len(prefix)>8:raise CommandError('invalid_environment')
    for key,value in variables.items():
        if not isinstance(value,str) or len(value)>8192 or '\0' in value:raise CommandError('invalid_environment')
        if key in PATH_ENV:
            candidate=Path(value)
            canonical(candidate if candidate.is_absolute() else upstream/candidate)
    for part in prefix:
        if not isinstance(part,str) or not Path(part).is_absolute():raise CommandError('invalid_environment')
        canonical(part)
    command=[str(python),'-s',STEPS[data['step']]]
    canonical(upstream/STEPS[data['step']])
    if data['step'] in ('sovits','gpt'):
        config=canonical(jobs/log.stem/('s2_config.json' if data['step']=='sovits' else 's1_config.yaml'))
        if not config.is_file():raise CommandError('missing_training_config')
        command+=['--config_file' if data['step']=='gpt' else '--config',str(config)]
    return command

def environment_delta(environment):
    base=os.environ
    if not set(base)<=set(environment):raise CommandError('invalid_environment')
    changed={key:value for key,value in environment.items() if base.get(key)!=value}
    path=changed.pop('PATH',None);prefix=[]
    if path is not None:
        original=base.get('PATH','')
        if original and not path.endswith(os.pathsep+original):raise CommandError('invalid_environment')
        extra=path[:-(len(original)+1)] if original else path
        prefix=extra.split(os.pathsep) if extra else []
    if not set(changed)<=ENV:raise CommandError('invalid_environment')
    return changed,prefix

class TrainingCommands:
    def __init__(self,upstream,jobs,*,python,timeout=21600,worker_factory=OwnedWorker):
        self.upstream=canonical(upstream);self.jobs=canonical(jobs);self.python=canonical(python)
        self.timeout=timeout;self.factory=worker_factory;self.lock=RLock();self.active=None;self.retained=None;self.closing=False;self.busy=False
    def run(self,step,*,environment,log_path,cancel=None):
        changes,prefix=environment_delta(environment)
        data=dict(version=1,step=step,python=str(self.python),upstream=str(self.upstream),jobs=str(self.jobs),log=str(canonical(log_path)),environment=changes,path_prefix=prefix)
        validate_request(data);encoded=json.dumps(data,ensure_ascii=False).encode('utf8')
        if len(encoded)>65536:raise CommandError('request_too_large')
        if not isinstance(self.timeout,(float,int)) or not 0<self.timeout<=86400:raise CommandError('invalid_timeout')
        owner=None
        with self.lock:
            if self.closing:raise CommandError('closed')
            if self.busy or self.retained is not None:raise CommandError('cleanup_pending_or_busy')
            self.busy=True
        try:
            folder=canonical(self.jobs/'.commands');folder.mkdir(exist_ok=True)
            folder=folder/uuid4().hex;folder.mkdir(exist_ok=False);request=folder/'request.json'
            with request.open('xb') as writer:writer.write(encoded)
            deadline=time.monotonic()+self.timeout
            with self.lock:
                if self.closing:raise CommandError('closed')
                owner=self.factory();self.active=owner
                owner.start([sys.executable,str(Path(__file__).resolve().parents[1]/'workers/training_command_worker.py'),str(request)],cwd=self.upstream)
            while True:
                if self.closing:raise CommandError('closed')
                if cancel is not None and cancel.is_set():raise CommandError('cancelled')
                if time.monotonic()>=deadline:raise CommandError('timed_out')
                code=owner.poll()
                if code is not None:
                    if code!=0:raise CommandError('exit_nonzero')
                    return
                time.sleep(.02)
        except OwnershipError as error:raise CommandError('ownership_failed') from error
        finally:
            with self.lock:
                self.busy=False
                if owner is not None:
                    try:owner.close()
                    except OwnershipError as error:
                        self.retained=owner;raise CommandError('cleanup_failed') from error
                    finally:self.active=None
    def retry_cleanup(self):
        with self.lock:
            if self.retained is not None:
                try:self.retained.close()
                except OwnershipError as error:raise CommandError('cleanup_failed') from error
                self.retained=None
    def close(self):
        with self.lock:
            self.closing=True
            if self.active is not None:
                try:self.active.close()
                except OwnershipError as error:
                    self.retained=self.active;raise CommandError('cleanup_failed') from error
            self.retry_cleanup()

_runner=None

def start_training_commands():
    global _runner
    from config import GPT_SOVITS_ROOT,GPT_SOVITS_PYTHON,TRAINING_JOBS_DIR,TRAINING_COMMAND_TIMEOUT
    if _runner is not None and (_runner.active is not None or _runner.retained is not None):raise CommandError('cleanup_pending_or_busy')
    _runner=TrainingCommands(GPT_SOVITS_ROOT,TRAINING_JOBS_DIR,python=GPT_SOVITS_PYTHON,timeout=TRAINING_COMMAND_TIMEOUT)

def close_training_commands():
    if _runner is not None:_runner.close()

def run_training_command(command,*,environment,log_path):
    if _runner is None:raise CommandError('not_initialized')
    if len(command)<3 or canonical(command[0])!=_runner.python or command[1]!='-s':raise CommandError('invalid_step')
    matches=[step for step,path in STEPS.items() if command[2]==path]
    if len(matches)!=1:raise CommandError('invalid_step')
    step=matches[0]
    expected=validate_request(dict(version=1,step=step,python=str(_runner.python),upstream=str(_runner.upstream),jobs=str(_runner.jobs),log=str(canonical(log_path)),environment={},path_prefix=[]))
    if command!=expected:raise CommandError('invalid_step')
    return _runner.run(step,environment=environment,log_path=log_path)
