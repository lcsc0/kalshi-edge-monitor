from collections import Counter
from dataclasses import dataclass
import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln

DEFAULT_HALF_LIFE_DAYS = 730.0


@dataclass(frozen=True)
class DCFit:
    attack: dict
    defense: dict
    home_adv: float
    rho: float


def _decay(date: str, ref: str, hl: float) -> float:
    age = (np.datetime64(ref) - np.datetime64(date[:10])).astype("timedelta64[D]").astype(int)
    return 0.5 ** (age / hl) if age >= 0 else 0.0


def fit_dixon_coles(conn, ref_date: str, since: str | None = None,
                    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
                    min_games: int = 20, max_iter: int = 500) -> DCFit:
    query = ("SELECT date, home_team, away_team, home_score, away_score, neutral "
             "FROM matches WHERE home_score IS NOT NULL AND away_score IS NOT NULL AND date < ?")
    args = [ref_date]
    if since:
        query += " AND date >= ?"
        args.append(since)
    rows = conn.execute(query, args).fetchall()

    cnt: Counter = Counter()
    for r in rows:
        cnt[r["home_team"]] += 1
        cnt[r["away_team"]] += 1
    teams = sorted(t for t, c in cnt.items() if c >= min_games)
    if not teams:
        return DCFit(attack={}, defense={}, home_adv=0.0, rho=0.0)
    idx = {t: i for i, t in enumerate(teams)}
    T = len(teams)

    rows = [r for r in rows if r["home_team"] in idx and r["away_team"] in idx]
    hi = np.array([idx[r["home_team"]] for r in rows])
    ai = np.array([idx[r["away_team"]] for r in rows])
    hs = np.array([r["home_score"] for r in rows], float)
    aw = np.array([r["away_score"] for r in rows], float)
    neu = np.array([1.0 if r["neutral"] else 0.0 for r in rows])
    w = np.array([_decay(r["date"], ref_date, half_life_days) for r in rows])
    lg_hs, lg_aw = gammaln(hs + 1), gammaln(aw + 1)

    def nll(p):
        """Weighted Dixon-Coles negative log-likelihood and its analytic gradient."""
        att, deff, home, rho = p[:T], p[T:2*T], p[2*T], p[2*T+1]
        log_lam = att[hi] - deff[ai] + home * (1 - neu)
        log_mu = att[ai] - deff[hi]
        lam, mu = np.exp(log_lam), np.exp(log_mu)
        t = np.ones_like(lam)
        d_ll = np.zeros_like(lam)   # d t / d log_lam
        d_lm = np.zeros_like(lam)   # d t / d log_mu
        d_rho = np.zeros_like(lam)  # d t / d rho
        m00 = (hs == 0) & (aw == 0)
        t[m00] = 1 - lam[m00]*mu[m00]*rho
        d_ll[m00] = d_lm[m00] = -lam[m00]*mu[m00]*rho
        d_rho[m00] = -lam[m00]*mu[m00]
        m01 = (hs == 0) & (aw == 1)
        t[m01] = 1 + lam[m01]*rho
        d_ll[m01] = lam[m01]*rho
        d_rho[m01] = lam[m01]
        m10 = (hs == 1) & (aw == 0)
        t[m10] = 1 + mu[m10]*rho
        d_lm[m10] = mu[m10]*rho
        d_rho[m10] = mu[m10]
        m11 = (hs == 1) & (aw == 1)
        t[m11] = 1 - rho
        d_rho[m11] = -1.0
        t = np.clip(t, 1e-9, None)
        ll = (hs*log_lam - lam - lg_hs) + (aw*log_mu - mu - lg_aw) + np.log(t)

        g_ll = w * (hs - lam + d_ll / t)   # d ll / d log_lam, weighted
        g_lm = w * (aw - mu + d_lm / t)    # d ll / d log_mu, weighted
        g_att = np.bincount(hi, g_ll, T) + np.bincount(ai, g_lm, T)
        g_def = -np.bincount(ai, g_ll, T) - np.bincount(hi, g_lm, T)
        g_home = np.sum(g_ll * (1 - neu))
        g_rho = np.sum(w * d_rho / t)
        grad = -np.concatenate([g_att, g_def, [g_home, g_rho]])
        return -np.sum(w * ll), grad

    x0 = np.concatenate([np.zeros(2*T), [0.25, -0.05]])
    bounds = [(-3, 3)]*(2*T) + [(1e-9, 1.0), (-0.2, 0.2)]
    res = minimize(nll, x0, jac=True, method="L-BFGS-B", bounds=bounds,
                   options={"maxiter": max_iter, "maxfun": 200000})
    att, deff, home, rho = res.x[:T], res.x[T:2*T], float(res.x[2*T]), float(res.x[2*T+1])
    shift = att.mean()
    att = att - shift
    deff = deff - shift
    return DCFit(attack={t: float(att[i]) for t, i in idx.items()},
                 defense={t: float(deff[i]) for t, i in idx.items()},
                 home_adv=home, rho=rho)
