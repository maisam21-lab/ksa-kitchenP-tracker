# Option 3: Use Trino from your PC via port-forward

So "Refresh from Trino" works on your laptop, forward the Trino gateway from the cluster to localhost.

## 1. Prerequisites

- **kubectl** installed and configured (you can run `kubectl get ns` and see your cluster).
- Access to the namespace where the presto-gateway service runs (often `presto-gateway`).

## 2. Start the port-forward

Open a **separate** terminal (keep it open while you use the tracker).

Run (adjust namespace/service if yours differ):

```bash
kubectl port-forward -n presto-gateway svc/presto-gateway 8080:80
```

You should see something like: `Forwarding from 127.0.0.1:8080 -> 80`

- If the **namespace** is different (e.g. `trino`), use: `-n trino`
- If the **service name** is different, list services: `kubectl get svc -n presto-gateway` and use that name.
- If **port 8080** is already in use on your PC, pick another (e.g. 9080) and change `.streamlit/secrets.toml`: set `TRINO_PORT = 9080`.

## 3. Secrets already set

The app is configured to use:

- **TRINO_HOST** = `127.0.0.1`
- **TRINO_PORT** = `8080`

So no change needed unless you used a different local port in step 2.

## 4. Run the tracker

In your **original** terminal:

```bat
cd C:\Users\MaysamAbuKashabeh\bi-etl-foundation
py -m streamlit run app/tracker_app.py --server.port 8502
```

Open the app, go to **Tracker** → expand **Refresh data from online sheet** → click **Refresh from Trino**.

## 5. When you're done

Stop the port-forward in the other terminal with **Ctrl+C**. Next time you want to use "Refresh from Trino", run the port-forward again.
