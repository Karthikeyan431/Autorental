import type { ComponentType } from 'react';

import AgreementsPage from '../features/agreements/AgreementsPage';
import AuditLogPage from '../features/audit/AuditLogPage';
import SignInPage from '../features/auth/SignInPage';
import AutosPage from '../features/autos/AutosPage';
import BankStatementsPage from '../features/bank-statements/BankStatementsPage';
import OwnerDashboardPage from '../features/dashboard/OwnerDashboardPage';
import StaffDashboardPage from '../features/dashboard/StaffDashboardPage';
import DriverDetailPage from '../features/drivers/DriverDetailPage';
import DriversListPage from '../features/drivers/DriversListPage';
import RegisterDriverPage from '../features/drivers/RegisterDriverPage';
import EscalationsPage from '../features/escalations/EscalationsPage';
import KycQueuePage from '../features/kyc/KycQueuePage';
import PayRequestsPage from '../features/pay-requests/PayRequestsPage';
import PaymentsPage from '../features/payments/PaymentsPage';
import ReportsPage from '../features/reports/ReportsPage';
import SettingsPage from '../features/settings/SettingsPage';
import StaffPage from '../features/staff/StaffPage';
import { strings } from '../lib/strings';

export type NavGroup = keyof typeof strings.nav.groups;

export type AppPage = {
  path: string;
  title: string;
  /** The milestone week that builds this screen. */
  week: number;
  Component: ComponentType;
  /** Shown in the sidebar. Sign-in and detail pages are not. */
  inNav: boolean;
  group: NavGroup;
  /** Rendered inside the app shell (everything except sign-in). */
  inShell: boolean;
};

const p = strings.pages;

/** One entry per screen in docs/requirements.md §4. Role-aware navigation comes in Week 2. */
export const APP_PAGES: AppPage[] = [
  {
    path: '/sign-in',
    title: p.signIn,
    week: 2,
    Component: SignInPage,
    inNav: false,
    group: 'overview',
    inShell: false,
  },
  {
    path: '/',
    title: p.ownerDashboard,
    week: 8,
    Component: OwnerDashboardPage,
    inNav: true,
    group: 'overview',
    inShell: true,
  },
  {
    path: '/my-dashboard',
    title: p.staffDashboard,
    week: 8,
    Component: StaffDashboardPage,
    inNav: true,
    group: 'overview',
    inShell: true,
  },
  {
    path: '/drivers',
    title: p.drivers,
    week: 3,
    Component: DriversListPage,
    inNav: true,
    group: 'drivers',
    inShell: true,
  },
  {
    path: '/drivers/new',
    title: p.registerDriver,
    week: 3,
    Component: RegisterDriverPage,
    inNav: true,
    group: 'drivers',
    inShell: true,
  },
  {
    path: '/drivers/:id',
    title: p.driver,
    week: 3,
    Component: DriverDetailPage,
    inNav: false,
    group: 'drivers',
    inShell: true,
  },
  {
    path: '/kyc',
    title: p.kycQueue,
    week: 3,
    Component: KycQueuePage,
    inNav: true,
    group: 'drivers',
    inShell: true,
  },
  {
    path: '/autos',
    title: p.autos,
    week: 4,
    Component: AutosPage,
    inNav: true,
    group: 'fleet',
    inShell: true,
  },
  {
    path: '/agreements',
    title: p.agreements,
    week: 5,
    Component: AgreementsPage,
    inNav: true,
    group: 'fleet',
    inShell: true,
  },
  {
    path: '/pay-requests',
    title: p.payRequests,
    week: 6,
    Component: PayRequestsPage,
    inNav: true,
    group: 'money',
    inShell: true,
  },
  {
    path: '/payments',
    title: p.payments,
    week: 6,
    Component: PaymentsPage,
    inNav: true,
    group: 'money',
    inShell: true,
  },
  {
    path: '/bank-statements',
    title: p.bankStatements,
    week: 7,
    Component: BankStatementsPage,
    inNav: true,
    group: 'money',
    inShell: true,
  },
  {
    path: '/escalations',
    title: p.escalations,
    week: 7,
    Component: EscalationsPage,
    inNav: true,
    group: 'money',
    inShell: true,
  },
  {
    path: '/reports',
    title: p.reports,
    week: 8,
    Component: ReportsPage,
    inNav: true,
    group: 'admin',
    inShell: true,
  },
  {
    path: '/staff',
    title: p.staff,
    week: 2,
    Component: StaffPage,
    inNav: true,
    group: 'admin',
    inShell: true,
  },
  {
    path: '/settings',
    title: p.settings,
    week: 2,
    Component: SettingsPage,
    inNav: true,
    group: 'admin',
    inShell: true,
  },
  {
    path: '/audit-log',
    title: p.auditLog,
    week: 8,
    Component: AuditLogPage,
    inNav: true,
    group: 'admin',
    inShell: true,
  },
];
