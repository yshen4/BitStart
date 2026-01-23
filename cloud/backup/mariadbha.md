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
```yaml
┌─────────────────────────────────────────────────────────────┐
│  1. Create Kubernetes client (in-cluster config)            │
│     clientset := kubernetes.NewForConfig(...)               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  2. Create BackupStorage via Factory                        │
│     backupStorage := cloud.NewBackupStorage(&logger)        │
│                                                             │
│     Factory reads CLOUD_PROVIDER env var and returns:       │
│     ┌─────────────────────────────────────────────────┐    │
│     │ "aws"   → AWSBackupStorage   (s3://bucket)      │    │
│     │ "azure" → AzureBackupStorage (azblob://container)│    │
│     │ "gcp"   → GCPBackupStorage   (gs://bucket)      │    │
│     └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  3. Create MariaDB HA backup job with interface             │
│     jobs.NewMariaDBHABackup(clientset, &logger, backupStorage)
│                                         ↑                   │
│                           BackupStorage interface           │
└─────────────────────────────────────────────────────────────┘
```

Here are sample code:
```go
// 1. Create Kubernetes client (in-cluster config)
clientset := kubernetes.NewForConfig(rest.InClusterConfig())

// 2. Create Cloud storage (validates provider config, builds bucket URL)
backupStorage := cloud.NewBackupStorage(&logger) 

// 3. Create MariaDB HA backup job
mariadbHABackUpJob := jobs.NewMariaDBHABackup(clientset, &logger, backupStorage)

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
5: Upload to Cloud via BackupStorage Interface
┌────────────────────────────────────────────────────────────┐
│  m.backupStorage.UploadBackup(ctx, file, "mariadb-ha-backup")
│         ↓                                                   │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Interface dispatches to concrete implementation:     │  │
│  │                                                      │  │
│  │ AWSBackupStorage.UploadBackup()                      │  │
│  │   → blob.OpenBucket("s3://bucket?region=us-west-2")  │  │
│  │   → bucket.Upload("mariadb-ha-backup/backup.tar.gz") │  │
│  │                                                      │  │
│  │ AzureBackupStorage.UploadBackup()                    │  │
│  │   → blob.OpenBucket("azblob://container")            │  │
│  │   → bucket.Upload("mariadb-ha-backup/backup.tar.gz") │  │
│  │                                                      │  │
│  │ GCPBackupStorage.UploadBackup()                      │  │
│  │   → blob.OpenBucket("gs://bucket")                   │  │
│  │   → bucket.Upload("mariadb-ha-backup/backup.tar.gz") │  │
│  └──────────────────────────────────────────────────────┘  │
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

## Implementation
```yaml
┌─────────────────────────────────────────────────────────────────────────┐
│                              main.go                                     │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  backupStorage := cloud.NewBackupStorage()  ← Factory Pattern   │    │
│  │  job := jobs.NewMariaDBHABackup(..., backupStorage)             │    │
│  │  job.Run()                                                       │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
┌─────────────────────────────┐     ┌─────────────────────────────────────┐
│    jobs/backup_mariadb_ha.go│     │         cloud/interface.go          │
│  ┌────────────────────────┐ │     │  ┌─────────────────────────────┐    │
│  │ mariaDBHABackup struct │ │     │  │  BackupStorage interface    │    │
│  │   backupStorage ───────┼─┼─────┼─▶│    UploadBackup()           │    │
│  │   (interface)          │ │     │  │    Provider()               │    │
│  └────────────────────────┘ │     │  └─────────────────────────────┘    │
│                             │     │              ▲                       │
│  - Get K8s secret           │     │              │ implements            │
│  - Run mariadb-dump         │     │     ┌───────┴───────┬───────────┐   │
│  - Compress                 │     │     │               │           │   │
│  - UploadBackup()           │     │     ▼               ▼           ▼   │
└─────────────────────────────┘     │ ┌───────┐     ┌─────────┐  ┌─────┐  │
                                    │ │aws.go │     │azure.go │  │gcp.go│ │
                                    │ │  AWS  │     │  Azure  │  │ GCP │  │
                                    │ │Backup │     │ Backup  │  │Backup│ │
                                    │ │Storage│     │ Storage │  │Storage│ │
                                    │ └───────┘     └─────────┘  └─────┘  │
                                    └─────────────────────────────────────┘
```

The interface defines cloud backup interface:
```go
// BackupStorage defines the interface for cloud storage operations.
// Implementations handle provider-specific logic for uploading backups.
type BackupStorage interface {
	// UploadBackup uploads a backup file to cloud storage.
	// backupFilePath is the local path to the file to upload.
	// blobDirName is the directory/prefix in the bucket where the file will be stored.
	UploadBackup(ctx context.Context, backupFilePath string, blobDirName string) error

	// Provider returns the name of the cloud provider (e.g., "aws", "azure", "gcp").
	Provider() string
}
```

Each of cloud providers implements this interface, for example AWSBackupStorage:
```go
// AWSConfig holds AWS S3 configuration.
type AWSConfig struct {
	Bucket string `env:"S3_BUCKET"`
	Region string `env:"S3_REGION"`
}

// AWSBackupStorage implements BackupStorage for AWS S3.
type AWSBackupStorage struct {
	config    AWSConfig
	bucketURL string
	logger    zerolog.Logger
}

// NewAWSBackupStorage creates a new AWS S3 backup storage.
func NewAWSBackupStorage(cfg AWSConfig, logger *zerolog.Logger) (*AWSBackupStorage, error) {
	if cfg.Bucket == "" {
		return nil, fmt.Errorf("s3 bucket not specified")
	}
	if cfg.Region == "" {
		return nil, fmt.Errorf("s3 region not specified")
	}

	return &AWSBackupStorage{
		config:    cfg,
		bucketURL: fmt.Sprintf(s3BucketURLFormat, cfg.Bucket, cfg.Region),
		logger:    logger.With().Str("provider", "aws").Logger(),
	}, nil
}

// UploadBackup uploads a backup file to AWS S3.
func (s *AWSBackupStorage) UploadBackup(ctx context.Context, backupFilePath string, blobDirName string) error {
	s.logger.Debug().Str("backup-file", backupFilePath).Msg("Uploading backup file to S3")

	backupFile, err := os.Open(backupFilePath)
	if err != nil {
		return fmt.Errorf("error opening backup file: %v", err)
	}
	defer backupFile.Close()

	blobKeyName := fmt.Sprintf("%s/%s", blobDirName, filepath.Base(backupFilePath))

	bucket, err := blob.OpenBucket(ctx, s.bucketURL)
	if err != nil {
		return fmt.Errorf("failed to open S3 bucket: %v", err)
	}
	defer bucket.Close()

	mimeType := getMimeType(backupFile.Name())
	err = bucket.Upload(ctx, blobKeyName, backupFile, &blob.WriterOptions{
		ContentType: mimeType,
	})
	if err != nil {
		return fmt.Errorf("failed to upload backup file to S3: %v", err)
	}

	s.logger.Debug().Str("key", blobKeyName).Msg("Successfully uploaded backup to S3")
	return nil
}

// Provider returns the cloud provider name.
func (s *AWSBackupStorage) Provider() string {
	return "aws"
}
```
