import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_trigger_appointment_reminders_endpoint():
    """Verify POST /api/tenants/cron/run-appointment-reminders executes and returns structured stats."""
    mock_stats = {
        "reminders_48h": 2,
        "reminders_24h": 1,
        "timeouts_processed": 0
    }
    with patch("app.services.appointment_service.AppointmentService.scan_and_send_appointment_reminders", new_callable=AsyncMock) as mock_scan:
        mock_scan.return_value = mock_stats
        
        # Test without parameters
        response = client.post("/api/tenants/cron/run-appointment-reminders")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["results"] == mock_stats
        
        # Test with optional hours_ahead parameter (backward-compatibility check)
        response_param = client.post("/api/tenants/cron/run-appointment-reminders?hours_ahead=24")
        assert response_param.status_code == 200
        assert response_param.json()["status"] == "success"

def test_trigger_secretary_shield_endpoint():
    """Verify POST /api/tenants/cron/run-secretary-shield runs across health tenants."""
    mock_batch = {"tenants_processed": 3, "reports_sent": 2}
    with patch("app.services.appointment_service.AppointmentService.broadcast_secretary_pre_cutoff_reports", new_callable=AsyncMock) as mock_shield:
        mock_shield.return_value = mock_batch
        
        response = client.post("/api/tenants/cron/run-secretary-shield")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["results"]["tenants_processed"] == 3
        assert data["results"]["reports_sent"] == 2

def test_trigger_cutoff_cancellations_endpoint():
    """Verify POST /api/tenants/cron/run-cutoff-cancellations runs 18hs auto-cutoff cascade."""
    mock_cutoff = {"tenants_processed": 3, "appointments_cancelled": 1}
    with patch("app.services.appointment_service.AppointmentService.execute_all_cutoff_auto_cancellations", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_cutoff
        
        response = client.post("/api/tenants/cron/run-cutoff-cancellations")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["results"]["appointments_cancelled"] == 1
