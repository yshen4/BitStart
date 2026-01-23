# MariaDH HA backup

```yaml
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ CronJob  │───▶│ Get K8s  │───▶│ mariadb- │───▶│ Compress │───▶│ Upload   │
│ triggers │    │ Secret   │    │ dump     │    │ .tar.gz  │    │ to Cloud │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
                     │               │               │               │
                     ▼               ▼               ▼               ▼
                 password      SQL dump file    .tar.gz +       s3/azblob/gs
                              (all databases)    .sha1          bucket path
```

## Step 1: Triggering (Kubernetes CronJob)
We deploy the backup as Kubernetes CronJob, which can be scheduled daily.

```yaml
┌─────────────────────────────────────────────────────────────┐
│  CronJob: platform-backup                                   │
│  Schedule: "0 4 * * *" (daily at 4 AM)                     │
│  Chart: charts/startree-backup                              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Pod starts with env vars:                                  │
│  - CLOUD_PROVIDER (aws/azure/gcp)                          │
│  - GCS_BUCKET / S3_BUCKET / AZURE_STORAGE_CONTAINER        │
│  - CELL_DEFAULT_NAMESPACE                                   │
│  - MARIADB_HA_SERVICE_NAME, MARIADB_HA_SECRET_NAME         │
└─────────────────────────────────────────────────────────────┘
```

## Step 2: Initialization

```go
// 1. Create Kubernetes client (in-cluster config)
clientset := kubernetes.NewForConfig(rest.InClusterConfig())

// 2. Create Cloud SDK (validates provider config, builds bucket URL)
cloudSdk := cloud.NewSDK()  // e.g., "gs://bucket" for GCP

// 3. Create MariaDB HA backup job
mariadbHABackUpJob := jobs.NewMariaDBHABackup(clientset, logger, cloudSdk)

// 4. Run the backup
mariadbHABackUpJob.Run(ctx)
```

## Step 3: Backup Execution
```go
1. Fetch Password from K8s Secret
┌────────────────────────────────────────────────────────────┐
│  secret := clientSet.CoreV1().Secrets(namespace).Get(     │
│      "mariadb",  // MARIADB_HA_SECRET_NAME                 │
│  )                                                         │
│  password := secret.Data["root-password"]                  │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
2: Create Temp Directory
┌────────────────────────────────────────────────────────────┐
│  tempPath := os.MkdirTemp("", "backup-ha-*")              │
│  dumpPath := tempPath + "/mariadb-ha-backup"              │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
3: Run mariadb-dump
┌────────────────────────────────────────────────────────────┐
│  mariadb-dump                                              │
│    --host=startree-mariadb-ha                             │
│    --port=3306                                             │
│    --user=root                                             │
│    --password=<from-secret>                                │
│    --single-transaction                                    │
│    --events                                                │
│    --routines                                              │
│    --all-databases                                         │
│    --skip-add-locks                                        │
│    --ignore-table=mysql.global_priv                        │
│    --result-file=/tmp/backup-ha-xxx/mariadb-ha-backup/    │
│                   all-databases-dump.sql                   │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
4: Compress Backup
┌────────────────────────────────────────────────────────────┐
│  utils.CompressBackup() creates:                           │
│    - mariadb-ha-backup.tar.gz                             │
│    - mariadb-ha-backup.tar.gz.sha1 (checksum)             │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
5: Upload to Cloud Storage
┌────────────────────────────────────────────────────────────┐
│  cloudSdk.UploadBlob(ctx, file, "mariadb-ha-backup")      │
│                                                            │
│  Uploads to:                                               │
│    AWS:   s3://bucket/mariadb-ha-backup/backup.tar.gz     │
│    Azure: azblob://container/mariadb-ha-backup/...        │
│    GCP:   gs://bucket/mariadb-ha-backup/...               │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
6: Cleanup
┌────────────────────────────────────────────────────────────┐
│  defer os.RemoveAll(tempPath)  // removes temp files       │
└────────────────────────────────────────────────────────────┘
```

## Step 4. Cloud Upload 
```go
// Build bucket URL based on provider
switch cloudProvider {
case "aws":   bucketURL = "s3://bucket?region=us-west-2"
case "azure": bucketURL = "azblob://container"
case "gcp":   bucketURL = "gs://bucket"
}

// Open bucket using gocloud.dev
bucket := blob.OpenBucket(ctx, bucketURL)

// Upload file
bucket.Upload(ctx, "mariadb-ha-backup/backup.tar.gz", file)
```
