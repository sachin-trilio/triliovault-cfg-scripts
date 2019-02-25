# Overview

TrilioVault Appliance charm is used to deploy a TrilioVault Appliance

# Usage

TrilioVault Appliance is deployed on a new machine in Juju Contoller
Steps to deploy the charm:

juju deploy trilio-appliance --config user-config.yaml --resource trilioimage=<absolute path for TrilioVault qcow2 image>

# Configuration

Please provide below configuration options using a config file:

triliovault-ip: IP Address of the TrilioVault Appliance

backup-target-type: Backup target type e.g. nfs or s3

For NFS backup target:

    nfs-shares: NFS Shares IP address only for nfs backup target

For Amazon S3 backup target:

    tv-s3-secret-key: S3 secret access key

    tv-s3-access-key: S3 access key

    tv-s3-region-name: S3 region name

    tv-s3-bucket: S3 bucket name

For non-AWS S3 backup target:

    tv-s3-secret-key: S3 secret access key

    tv-s3-access-key: S3 access key

    tv-s3-endpoint-url: S3 endpoint URL

    tv-s3-region-name: S3 region name

    tv-s3-bucket: S3 bucket name

TrilioVault appliance should be up and running before deploying this charm.

The configuration options need to be updated based on the S3 specific requirements and the parameters that are not needed can be omitted.

# Contact Information

Trilio Support <support@trilio.com>
