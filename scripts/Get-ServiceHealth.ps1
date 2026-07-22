<#
.SYNOPSIS
    Quick operational health check for the LexisNexis reference project's
    ECS service, ALB target health, and any active CloudWatch alarms.

.DESCRIPTION
    Shells out to the AWS CLI (already authenticated via the
    cdk-deploy-static profile) rather than requiring the full AWS.Tools
    PowerShell module - keeps this genuinely runnable without extra setup.
#>

param(
    [string]$Profile = "cdk-deploy-static",
    [string]$Region = "eu-west-1",
    [string]$Cluster = "LxnDemo-Compute-ClusterEB0386A7-TQudU7Szuw4g",
    [string]$Service = "LxnDemo-Compute-ServiceD69D759B-cpZwCLZHH0dn"
)

function Get-EcsServiceHealth {
    Write-Host "`n== ECS Service Health ==" -ForegroundColor Cyan
    $result = aws ecs describe-services `
        --cluster $Cluster `
        --services $Service `
        --profile $Profile `
        --region $Region | ConvertFrom-Json

    $svc = $result.services[0]
    [PSCustomObject]@{
        Status       = $svc.status
        Running      = $svc.runningCount
        Desired      = $svc.desiredCount
        Deployment   = $svc.deployments[0].rolloutState
    } | Format-Table -AutoSize

    if ($svc.runningCount -lt $svc.desiredCount) {
        Write-Host "WARNING: running count is below desired count." -ForegroundColor Yellow
    } else {
        Write-Host "OK: running count matches desired count." -ForegroundColor Green
    }
}

function Get-ActiveAlarms {
    Write-Host "`n== Active CloudWatch Alarms ==" -ForegroundColor Cyan
    $alarms = aws cloudwatch describe-alarms `
        --state-value ALARM `
        --profile $Profile `
        --region $Region | ConvertFrom-Json

    $ours = $alarms.MetricAlarms | Where-Object { $_.AlarmName -like "LxnDemo-Observability*" }

    if ($ours.Count -eq 0) {
        Write-Host "OK: no LxnDemo alarms currently in ALARM state." -ForegroundColor Green
    } else {
        $ours | Select-Object AlarmName, StateReason | Format-Table -AutoSize -Wrap
        Write-Host "WARNING: $($ours.Count) alarm(s) active - see above." -ForegroundColor Yellow
    }
}

function Get-AlbTargetHealth {
    Write-Host "`n== ALB Target Health ==" -ForegroundColor Cyan
    $tg = aws elbv2 describe-target-groups `
        --profile $Profile --region $Region `
        --query "TargetGroups[0].TargetGroupArn" `
        --output text

    if (-not $tg) {
        Write-Host "Could not find target group - check the name filter." -ForegroundColor Yellow
        return
    }

    $health = aws elbv2 describe-target-health `
        --target-group-arn $tg `
        --profile $Profile --region $Region | ConvertFrom-Json

    $health.TargetHealthDescriptions | ForEach-Object {
        [PSCustomObject]@{
            Target = $_.Target.Id
            Port   = $_.Target.Port
            State  = $_.TargetHealth.State
        }
    } | Format-Table -AutoSize
}


function Restart-Deployment {
    <#
    .SYNOPSIS
        Forces a new ECS deployment - the same action the GitHub Actions
        pipeline runs automatically after a successful image build/push.
    #>
    Write-Host "`n== Forcing New Deployment ==" -ForegroundColor Cyan
    $result = aws ecs update-service `
        --cluster $Cluster `
        --service $Service `
        --force-new-deployment `
        --profile $Profile `
        --region $Region | ConvertFrom-Json

    Write-Host "Deployment triggered. New deployment ID:" -ForegroundColor Green
    $result.service.deployments[0].id
}

function Get-RecentLogs {
    <#
    .SYNOPSIS
        Tails the app's CloudWatch logs for the last hour - quick way to
        confirm the running container is actually serving what you expect.
    #>
    param([string]$LogGroup = "LxnDemo-Compute-TaskDefAppContainerLogGroup3E3EEE65-AZbs6joGYnFQ", [string]$Since = "1h")

    Write-Host "`n== Recent App Logs (last $Since) ==" -ForegroundColor Cyan
    aws logs tail $LogGroup --since $Since --profile $Profile --region $Region
}

# --- Run all checks ---
Write-Host "LexisNexis reference project - operational health check" -ForegroundColor Magenta
Write-Host "Profile: $Profile | Region: $Region`n"

Get-EcsServiceHealth
Get-ActiveAlarms
Get-AlbTargetHealth
