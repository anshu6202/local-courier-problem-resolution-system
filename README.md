# local-courier-problem-resolution-system

## Complaint SLA checks

The Django command is idempotent and can be run manually from `courier_resolution`:

```powershell
python manage.py check_sla_breaches
```

It checks active complaints, creates one approaching-deadline notification per admin and complaint, and records/escalates breached complaints once. The approaching window defaults to 4 hours; set `COMPLAINT_SLA_APPROACHING_HOURS=0` to disable that alert or choose another non-negative number. Apply the database migration before running the command.

Run it every five minutes with the host's scheduler. This repository does not identify a production host, so no platform scheduler is deployed or claimed as active.

On Linux/Unix, add a cron entry using the actual project and virtual-environment paths:

```cron
*/5 * * * * cd /path/to/courier_resolution && /path/to/venv/bin/python manage.py check_sla_breaches >> /path/to/logs/complaint-sla.log 2>&1
```

On Windows, create a Task Scheduler task with a five-minute repeat interval. Set **Program/script** to the project's virtual environment `Scripts\python.exe`, **Arguments** to `manage.py check_sla_breaches`, and **Start in** to the `courier_resolution` directory. Configure the task to run under the deployment account that has access to the app's environment variables and database. Verify execution in Task Scheduler history and by checking that overdue complaints become escalated and admin alerts appear.

The app has no configured SMTP backend outside Django's debug console backend, so alerts are in-app only. Admins can view them from the dashboard's **View notifications** link. Marking an alert read requires an authenticated admin POST.