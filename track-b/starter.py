"""Optional, correct stdlib loader. Extend this with your own experiment."""
import csv
import json
from pathlib import Path


DATA = Path(__file__).resolve().parent / 'data'


def load_csv(name):
    with (DATA / name).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def load_inputs():
    return {
        'scenario': json.loads((DATA / 'scenario.json').read_text(encoding='utf-8')),
        'cases': load_csv('cases.csv'),
        'events': load_csv('events.csv'),
        'requests': load_csv('requests.csv'),
    }


if __name__ == '__main__':
    inputs = load_inputs()
    print('Daybreak Repairs | synthetic data loaded')
    print('Snapshot:', inputs['scenario']['snapshot_at'])
    for key in ('cases', 'events', 'requests'):
        print(f'{key}: {len(inputs[key])} exported rows')
    print('Next: inspect the records, choose a question and build your experiment.')
