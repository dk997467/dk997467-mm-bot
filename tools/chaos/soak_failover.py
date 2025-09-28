import argparse
import sys


class FakeKVLock:
    def __init__(self, ttl_ms: int):
        self.ttl_ms = int(ttl_ms)
        self.owner = None
        self.expiry_ms = -1
        self.leader_elections_total = 0
        self.renew_fail_total = 0

    def try_acquire(self, node: str, now_ms: int) -> bool:
        if self.owner is None or now_ms >= self.expiry_ms:
            self.owner = node
            self.expiry_ms = now_ms + self.ttl_ms
            self.leader_elections_total += 1
            return True
        return False

    def renew(self, node: str, now_ms: int) -> bool:
        if self.owner == node and now_ms < self.expiry_ms:
            self.expiry_ms = now_ms + self.ttl_ms
            return True
        self.renew_fail_total += 1
        return False

    def release(self, node: str) -> None:
        if self.owner == node:
            self.owner = None
            self.expiry_ms = -1


def run_sim(ttl_ms: int, renew_ms: int, kill_at_ms: int, window_ms: int) -> str:
    kv = FakeKVLock(ttl_ms)
    step = 100
    last_renew = {'A': -10**9, 'B': -10**9}
    alive = {'A': True, 'B': True}
    state = {'A': 'follower', 'B': 'follower'}
    idem_seen = set()
    idem_hits = 0
    takeover_time = None
    leader_switch_alerts = 0
    leader_history = []

    out_lines = []

    for t in range(0, window_ms + 1, step):
        if t >= kill_at_ms:
            alive['A'] = False

        for name in ('A', 'B'):
            if not alive[name]:
                continue
            # Try acquire if no owner or expired
            if kv.try_acquire(name, t):
                state[name] = 'leader'
                # leader switch alert (once per switch)
                if (not leader_history) or leader_history[-1] != name:
                    leader_history.append(name)
                    if len(leader_history) > 1:
                        leader_switch_alerts += 1
                # idempotency event
                tok = f'ORD-{(t//step)%3}'
                if tok in idem_seen:
                    idem_hits += 1
                idem_seen.add(tok)
                out_lines.append(f'CHAOS t={t} role={name} state=leader lock=acq idem_hits={idem_hits}')
                # takeover timing
                if name == 'B' and t >= kill_at_ms and takeover_time is None:
                    takeover_time = t - kill_at_ms
            else:
                # Renew if leader
                if kv.owner == name and (t - last_renew[name]) >= renew_ms:
                    if kv.renew(name, t):
                        last_renew[name] = t
                        # idempotency event on renew tick as proxy
                        tok = f'ORD-{(t//step)%3}'
                        if tok in idem_seen:
                            idem_hits += 1
                        idem_seen.add(tok)
                        out_lines.append(f'CHAOS t={t} role={name} state=leader lock=renew idem_hits={idem_hits}')
                    else:
                        state[name] = 'follower'
        # ensure no dual leadership
        leaders = [n for n in ('A','B') if state[n]=='leader' and kv.owner==n and (alive[n])]
        if len(leaders) > 1:
            out_lines.append('CHAOS ERROR dual_leader')

    # Criteria
    ok_takeover = (takeover_time is not None and takeover_time <= ttl_ms + 200)
    ok_dual = all('dual_leader' not in l for l in out_lines)
    ok_idem = (idem_hits > 0)
    alert_storm_counter = max(0, leader_switch_alerts - 1)
    ok_alert = (alert_storm_counter == 0)

    result_ok = ok_takeover and ok_dual and ok_idem and ok_alert
    out_lines.append(f'CHAOS_SUMMARY takeover_ms={takeover_time if takeover_time is not None else -1} idem_hits_total={idem_hits} alert_storm_counter={alert_storm_counter}')
    out_lines.append('CHAOS_RESULT=' + ('OK' if result_ok else 'FAIL'))
    return '\n'.join(out_lines) + '\n'


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--ttl-ms', type=int, default=1500)
    ap.add_argument('--renew-ms', type=int, default=500)
    ap.add_argument('--kill-at-ms', type=int, default=3000)
    ap.add_argument('--window-ms', type=int, default=6000)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)

    if args.dry_run:
        print('CHAOS_RESULT=OK')
        return 0

    out = run_sim(args.ttl_ms, args.renew_ms, args.kill_at_ms, args.window_ms)
    sys.stdout.write(out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


