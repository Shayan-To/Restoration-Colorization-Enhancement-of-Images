import os
import sys

script_dir = os.path.abspath(os.path.dirname(__file__))

sys.path.append(script_dir)
os.environ["PYTHONPATH"] = script_dir
