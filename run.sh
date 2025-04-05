#!/bin/bash
#SBATCH --job-name=demand_1
#SBATCH --qos=normal
#SBATCH --mem=32G
#SBATCH --cpus-per-task=8
#SBATCH --partition=cpu

REGION_IDX="1"
PATH_PROGRAM="$HOME/Ile-de-france"
PRINTS_SAVE_PATH="$HOME/Ile-de-france/printouts/out_$REGION_IDX.txt"
REGION_ARG="region_$REGION_IDX"

cd "$PATH_PROGRAM"
source activate convert_demand
mkdir -p printouts
python -u demand_converter.py --region "$REGION_ARG" > "$PRINTS_SAVE_PATH" 2>&1