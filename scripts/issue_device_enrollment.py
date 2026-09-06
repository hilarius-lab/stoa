import argparse,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from smart_notebook.database import init_db
from smart_notebook.services.device_auth import issue_enrollment_code
parser=argparse.ArgumentParser();parser.add_argument("--minutes",type=int,default=15)
args=parser.parse_args();init_db();print(issue_enrollment_code(args.minutes))
