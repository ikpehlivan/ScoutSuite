#!/usr/bin/env python2

# Import AWS Scout2 tools
from AWSScout2.utils import *
from AWSScout2.utils_cloudtrail import *
from AWSScout2.utils_ec2 import *
from AWSScout2.utils_iam import *
from AWSScout2.utils_rds import *
from AWSScout2.utils_s3 import *

# Import other third-party packages
import os
import traceback


########################################
##### Main
########################################

def main(args):

    key_id = None
    secret = None
    mfa_serial = None
    session_token = None

    # Create the list of services to analyze
    services = build_services_list(args.services, args.skipped_services)
    if not len(services):
        print 'Error: list of Amazon Web Services to be analyzed is empty.'
        return

    # Check the version of boto
    if not args.fetch_local and not check_boto_version():
        return

    # Fetch credentials from the EC2 instance's metadata
    if args.fetch_creds_from_instance_metadata:
        key_id, secret = fetch_iam_role_credentials()

    # Fetch credentials from AWS config
    if args.fetch_creds_from_aws_cli_config:
        key_id, secret, session_token = fetch_creds_from_aws_cli_config()

    # Fetch credentials from CSV
    if args.fetch_creds_from_csv is not None:
        key_id, secret, mfa_serial = fetch_creds_from_csv(args.fetch_creds_from_csv[0])

    # Fetch credentials from environment
    if key_id is None and secret is None and 'AWS_ACCESS_KEY_ID' in os.environ and 'AWS_SECRET_ACCESS_KEY' in os.environ:
        key_id = os.environ["AWS_ACCESS_KEY_ID"]
        secret = os.environ["AWS_SECRET_ACCESS_KEY"]

    if not args.fetch_local and (key_id is None or secret is None):
        print 'Error: could not find AWS credentials. Use the --help option for more information.'
        return -1

    # Fetch STS credentials
    if args.mfa_serial:
        mfa_serial = args.mfa_serial[0]
    if args.mfa_code:
        key_id, secret, session_token = fetch_sts_credentials(key_id, secret, mfa_serial, args.mfa_code)

    # Load findings from JSON config files
    for service in services:
        load_findings(service, args.ruleset_name)

    ##### CloudTrail
    if 'cloudtrail' in services:
        # Fetch data from AWS or an existing local file
        if not args.fetch_local:
            cloudtrail_info = get_cloudtrail_info(key_id, secret, session_token)
        else:
            cloudtrail_info = load_info_from_json('cloudtrail', args.environment_name)
        # Analyze the CloudTrail config and save data to a local file
        analyze_cloudtrail_config(cloudtrail_info, args.force_write)

    ##### IAM
    if 'iam' in services:
        # Fetch data from AWS or an existing local file
        if not args.fetch_local:
            iam_info = get_iam_info(key_id, secret, session_token)
        else:
            iam_info = load_info_from_json('iam', args.environment_name)
        # Analyze the IAM config and save data to a local file
        if 'ec2' not in services:
            analyze_iam_config(iam_info, args.force_write)

    ##### EC2
    if 'ec2' in services:
        # Fetch data from AWS or an existing local file
        if not args.fetch_local:
            ec2_info = get_ec2_info(key_id, secret, session_token, args.fetch_gov)
        else:
            ec2_info = load_info_from_json('ec2', args.environment_name)
        # Analyze the EC2 config and save data to a local file
        analyze_ec2_config(ec2_info, args.force_write)

    ##### RDS
    if 'rds' in services:
        if not args.fetch_local:
            rds_info = get_rds_info(key_id, secret, session_token, args.fetch_gov)
        else:
            rds_info = load_info_from_json('rds', args.environment_name)
        analyze_rds_config(rds_info, args.force_write)

    ##### S3
    if 's3' in services:
        if not args.fetch_local:
            s3_info = get_s3_info(key_id, secret, session_token, args.check_s3_encryption, args.check_s3_acls)
        else:
            s3_info = load_info_from_json('s3', args.environment_name)
        # Analyze the S3 config and save data to a local file
        analyze_s3_config(s3_info, args.force_write)


    ##### Analyzis that requires multiple configuration
    if 'ec2' in services and 'iam' in services:
        match_instances_and_roles(ec2_info, iam_info)
        analyze_iam_config(iam_info, args.force_write)
    if 'cloudtrail' in services and 'ec2' in services:
        refine_cloudtrail(cloudtrail_info, ec2_info)
        save_config_to_file(cloudtrail_info, 'cloudtrail', args.force_write)


    ##### Rename data based on environment's name
    if args.environment_name:
        create_new_scout_report(args.environment_name, args.force_write)


########################################
##### Argument parser
########################################

parser.add_argument('--gov',
                    dest='fetch_gov',
                    default=False,
                    action='store_true',
                    help='fetch the EC2 configuration from the us-gov-west-1 region')
parser.add_argument('--role_credentials',
                    dest='fetch_creds_from_instance_metadata',
                    default=False,
                    action='store_true',
                    help='fetch credentials for this EC2 instance')
parser.add_argument('--aws_cli_credentials',
                    dest='fetch_creds_from_aws_cli_config',
                    default=False,
                    action='store_true',
                    help='fetch credentials from the AWS CLI configuration file')
parser.add_argument('--csv_credentials',
                    dest='fetch_creds_from_csv',
                    default=None,
                    nargs='+',
                    help='fetch credentials from a CSV file')
parser.add_argument('--mfa_serial',
                    dest='mfa_serial',
                    default=None,
                    nargs='+',
                    help='MFA device\'s serial number')
parser.add_argument('--mfa_code',
                    dest='mfa_code',
                    default=None,
                    nargs='+',
                    help='MFA code')
parser.add_argument('--local',
                    dest='fetch_local',
                    default=False,
                    action='store_true',
                    help='use local data previously fetched to feed the analyzer')
parser.add_argument('--env',
                    dest='environment_name',
                    default=None,
                    nargs='+',
                    help='AWS environment name (used to create multiple reports)')
parser.add_argument('--check_s3_encryption',
                    dest='check_s3_encryption',
                    default=None,
                    nargs='*',
                    help='list of S3 buckets to iterate through; pulls server-side encryption settings for each object in bucket (Slow)')
parser.add_argument('--check_s3_acls',
                    dest='check_s3_acls',
                    default=None,
                    nargs='*',
                    help='list of S3 buckets to iterate through; pulls permissions for each object in bucket (Slow)')

args = parser.parse_args()

if __name__ == '__main__':
    main(args)
