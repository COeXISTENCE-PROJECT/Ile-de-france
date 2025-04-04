#!/bin/bash
#SBATCH --job-name=demand_convert
#SBATCH --qos=normal
#SBATCH --mem=32G
#SBATCH --cpus-per-task=8
#SBATCH --partition=cpu

PATH_PROGRAM="$HOME/Ile-de-france"
PRINTS_SAVE_PATH="$HOME/Ile-de-france/printouts/out_$SLURM_JOB_ID.txt"

cd "$PATH_PROGRAM"
conda activate convert_demand
mkdir -p printouts
python -u demand_converter.py > "$PRINTS_SAVE_PATH" 2>&1