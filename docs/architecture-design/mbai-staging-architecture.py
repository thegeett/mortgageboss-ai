from diagrams import Diagram, Cluster, Edge
from diagrams.aws.general import Users
from diagrams.aws.network import Route53, ElbApplicationLoadBalancer, Endpoint
from diagrams.aws.security import Cognito, CertificateManager, SecretsManager, KMS
from diagrams.aws.compute import Fargate, ECR
from diagrams.aws.database import RDS, ElastiCache
from diagrams.aws.storage import S3
from diagrams.aws.ml import Bedrock
from diagrams.aws.management import Cloudwatch

graph_attr = {"fontsize": "16", "bgcolor": "white", "pad": "0.5",
              "splines": "spline", "nodesep": "0.9", "ranksep": "1.1",
              "fontname": "Helvetica", "compound": "true"}
node_attr = {"fontsize": "11", "fontname": "Helvetica"}
edge_attr = {"fontsize": "10", "fontname": "Helvetica", "labeldistance": "1.2"}

with Diagram("MortgageBoss AI — staging   ·   AWS account 058190633983   ·   us-east-1",
             filename="mbai-staging-architecture", show=False, direction="TB",
             graph_attr=graph_attr, node_attr=node_attr, edge_attr=edge_attr):

    users = Users("Loan processor\nbrowser")

    with Cluster("Edge — authentication happens BEFORE any task is reached"):
        dns = Route53("Route 53\nstaging.mortgageboss.ai")
        cognito = Cognito("Cognito\nuser pool")
        acm = CertificateManager("ACM\nTLS 1.3")

    with Cluster("VPC  ·  public subnets (2 AZ)"):
        alb = ElbApplicationLoadBalancer("Application Load Balancer\nHTTP 80 → 301 → HTTPS 443")

    with Cluster("VPC  ·  private subnets  ·  single AZ  ·  NO route to internet"):
        with Cluster("ECS Fargate  ·  ARM64  ·  desired_count = 1"):
            fe  = Fargate("frontend\nNext.js :3000")
            api = Fargate("api\nFastAPI :8000")
            wkr = Fargate("worker\nCelery")

        with Cluster("Data tier"):
            redis = ElastiCache("ElastiCache Redis 7.1\nTLS + AUTH token")
            rds   = RDS("RDS Postgres 16\nrds.force_ssl = 1")

        vpce = Endpoint("VPC endpoints\n5 interface + S3 gateway")

    with Cluster("AWS services  ·  reached ONLY through the endpoints above"):
        bedrock = Bedrock("Bedrock\nHaiku 4.5 · Sonnet 4.5")
        s3      = S3("S3 documents\nSSE-KMS")
        sm      = SecretsManager("Secrets Manager\n4 secrets")
        ecr     = ECR("ECR\napi · frontend")
        cw      = Cloudwatch("CloudWatch Logs")
        kms     = KMS("KMS CMK")

    # request path
    users   >> Edge(label="HTTPS", color="darkgreen", penwidth="2") >> dns
    dns     >> Edge(label="alias") >> alb
    acm     >> Edge(style="dashed", color="gray50", label="cert") >> alb
    cognito >> Edge(color="firebrick", fontcolor="firebrick", penwidth="2",
                    label="auth on EVERY\nlistener rule") >> alb

    alb >> Edge(label="default") >> fe
    alb >> Edge(label="/api/*") >> api

    # app internals
    api   >> Edge(label="enqueue") >> redis
    redis >> Edge(label="consume") >> wkr
    api   >> Edge(label="SQL") >> rds
    wkr   >> Edge(label="SQL") >> rds

    # egress
    fe  >> Edge(style="invis") >> vpce
    api >> Edge(label="Put/GetObject") >> vpce
    wkr >> Edge(label="GetObject +\nInvokeModel") >> vpce

    vpce >> Edge(color="darkorange", fontcolor="darkorange", penwidth="2",
                 label="worker ONLY\napi has no Bedrock") >> bedrock
    vpce >> Edge(label="api rw · worker r") >> s3
    vpce >> Edge(label="at task start") >> sm
    vpce >> Edge(label="image pull") >> ecr
    vpce >> Edge(label="stdout") >> cw
    kms  >> Edge(style="dashed", color="gray50", label="encrypts") >> s3
    kms  >> Edge(style="dashed", color="gray50") >> sm
