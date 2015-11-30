# oe_autobackups
Automatic database backups for OperERP 7.0 with file rotation.

## Documentation

The module adds the Autobackups entry under Settings => Configuration.

### Configuration

Configuration defines the shared parameters for each backup job.
Mandatories:
- Main Backup Folder: 
    A valid path on the server used to store backups files
Optionals:
- External Last Backup Folder:  
    A valid path on the server used to store only the last backup (planned scp/ftp support)
- Backup History: 
    Number of backups to keep
- Backup Frequency: 
    Backup frequency (integer)
- Frequency Unit: 
    Unit of measure of backup frequency (available: Minutes, Hours, Days, Weeks, Months)

### Backup Jobs

Backup Jobs:
  Definition and management of active backups
