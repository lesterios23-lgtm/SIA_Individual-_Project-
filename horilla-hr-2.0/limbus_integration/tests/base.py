"""Shared fixtures for the HR Limbus integration tests."""

from __future__ import annotations

from datetime import date

from base.models import Department, JobPosition
from employee.models import Employee
from horilla.testkit import CompanyFilterTestMixin, clear_selected_company, make_company, make_employee


class EmployeeFixtureMixin(CompanyFilterTestMixin):
    @classmethod
    def setUpTestData(cls):
        clear_selected_company()
        cls.company = make_company("Limbus HR Test Co")
        cls.department = Department.objects.create(department="Manufacturing")
        cls.department.company_id.add(cls.company)
        cls.job_position = JobPosition.objects.create(
            job_position="Machine Operator", department_id=cls.department
        )
        cls.manager = cls._make_employee(
            badge="EMP-000",
            email="manager@test.horilla",
            first_name="Mona",
            last_name="Manager",
        )

    @classmethod
    def _make_employee(
        cls,
        *,
        badge,
        email,
        first_name="Test",
        last_name="Operator",
        active=True,
    ):
        employee = make_employee(
            company=cls.company,
            email=email,
            first_name=first_name,
            last_name=last_name,
            date_joining=date(2025, 1, 6),
        )
        employee.badge_id = badge
        employee.is_active = active
        employee.save()
        work_info = employee.employee_work_info
        work_info.department_id = cls.department
        work_info.job_position_id = cls.job_position
        manager = getattr(cls, "manager", None)
        if manager is not None:
            work_info.reporting_manager_id = manager
        work_info.date_joining = date(2025, 1, 6)
        work_info.contract_end_date = date(2026, 1, 5)
        work_info.save()
        return Employee.objects.select_related(
            "employee_work_info",
            "employee_work_info__department_id",
            "employee_work_info__job_position_id",
            "employee_work_info__reporting_manager_id",
        ).get(pk=employee.pk)

    def make_operator(self, badge="EMP-001", email="operator@test.horilla", active=True):
        return self._make_employee(
            badge=badge, email=email, active=active
        )
