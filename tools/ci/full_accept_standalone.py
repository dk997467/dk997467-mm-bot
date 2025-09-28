import sys, json, os, argparse
def load_json(p): 
    with open(p,'r',encoding='utf-8') as f: return json.load(f)
def err(msg,file): 
    print(f"event=accept_error file={file} reason={msg}"); return 1
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--artifacts-dir',default='artifacts'); a=ap.parse_args()
    ad=a.artifacts_dir; errors=0; checked=0
    # KPI_GATE.json
    p=os.path.join(ad,'KPI_GATE.json')
    try:
        j=load_json(p); checked+=1
        if not isinstance(j.get('timestamp'),(int,float)): errors+=err('bad_timestamp','KPI_GATE.json')
        if not isinstance(j.get('readiness'),(int,float)): errors+=err('bad_readiness','KPI_GATE.json')
        checks=j.get('checks')
        if not (isinstance(checks,(list,dict)) and len(checks)>0): errors+=err('bad_checks','KPI_GATE.json')
    except: errors+=err('load_fail','KPI_GATE.json')
    # FULL_STACK_VALIDATION.json
    p=os.path.join(ad,'FULL_STACK_VALIDATION.json')
    try:
        j=load_json(p); checked+=1
        if j.get('status') not in ('OK','FAIL'): errors+=err('bad_status','FULL_STACK_VALIDATION.json')
        comps=j.get('components')
        if not (isinstance(comps,list) and len(comps)>0): errors+=err('bad_components','FULL_STACK_VALIDATION.json')
        if not isinstance(j.get('ts'),(int,float)): errors+=err('bad_ts','FULL_STACK_VALIDATION.json')
    except: errors+=err('load_fail','FULL_STACK_VALIDATION.json')
    # EDGE_REPORT.json
    p=os.path.join(ad,'EDGE_REPORT.json')
    try:
        j=load_json(p); checked+=1
        if not isinstance(j.get('net_bps'),(int,float)): errors+=err('bad_net_bps','EDGE_REPORT.json')
        lat=j.get('latency',{})
        for k in ('p50','p95','p99'):
            if not isinstance(lat.get(k),(int,float)): errors+=err(f'bad_latency_{k}','EDGE_REPORT.json')
        tr=j.get('taker_ratio')
        if not (isinstance(tr,(int,float)) and 0.0<=tr<=1.0): errors+=err('bad_taker_ratio','EDGE_REPORT.json')
    except: errors+=err('load_fail','EDGE_REPORT.json')
    # EDGE_SENTINEL.json
    p=os.path.join(ad,'EDGE_SENTINEL.json')
    try:
        j=load_json(p); checked+=1
        b=j.get('buckets')
        if not ((isinstance(b,list) or isinstance(b,dict)) and len(b)>0): errors+=err('bad_buckets','EDGE_SENTINEL.json')
        if not isinstance(j.get('advice'),str): errors+=err('bad_advice','EDGE_SENTINEL.json')
        if not isinstance(j.get('ts'),(int,float)): errors+=err('bad_ts','EDGE_SENTINEL.json')
    except: errors+=err('load_fail','EDGE_SENTINEL.json')
    status='OK' if errors==0 else 'FAIL'
    print(f"event=full_accept status={status} files_checked={checked} errors={errors}")
    sys.exit(0 if errors==0 else 1)
if __name__=='__main__': main()
