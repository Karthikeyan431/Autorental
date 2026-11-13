import type { ComponentType } from 'react';

import AgreementsPage from '../features/agreements/AgreementsPage';
import AuditLogPage from '../features/audit/AuditLogPage';
import type { Role, User } from '../features/auth/api';
import ChangePasswordPage from '../features/auth/ChangePasswordPage';
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

/** Who may open a page. No rule: anyone signed in. The owner has every permission. */
export type PageAccess = { role?: Role; permission?: string };

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
  access?: PageAccess;
};

const p = strings.pages;

/** One entry per screen in docs/requirements.md §4, plus the change-password page. */
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
    week: 2, // shell now; filled in by later weeks
    Component: OwnerDashboardPage,
    inNav: true,
    group: 'overview',
    inShell: true,
    access: { role: 'owner' },
  },
  {
    path: '/my-dashboard',
    title: p.staffDashboard,
    week: 2, // shell now; filled in by later weeks
    Component: StaffDashboardPage,
    inNav: true,
    group: 'overview',
    inShell: true,
    access: { role: 'staff' },
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
    access: { permission: 'statements.upload' },
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
    access: { permission: 'users.manage' },
  },
  {
    path: '/settings',
    title: p.settings,
    week: 2,
    Component: SettingsPage,
    inNav: true,
    group: 'admin',
    inShell: true,
    access: { permission: 'settings.manage' },
  },
  {
    path: '/audit-log',
    title: p.auditLog,
    week: 2, // shell now; filled in by later weeks
    Component: AuditLogPage,
    inNav: true,
    group: 'admin',
    inShell: true,
    access: { permission: 'audit.view' },
  },
  {
    path: '/change-password',
    title: p.changePassword,
    week: 2,
    Component: ChangePasswordPage,
    inNav: false,
    group: 'admin',
    inShell: true,
  },
];

export function canOpen(page: AppPage, user: User): boolean {
  const { role, permission } = page.access ?? {};
  if (role && user.role !== role) return false;
  if (permission && !user.permissions.includes(permission)) return false;
  return true;
}
