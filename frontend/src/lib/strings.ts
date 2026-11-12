/**
 * All user-facing English text lives here, so a regional language can be added later (Q30).
 * Components import from this file instead of writing text inline.
 */
export const strings = {
  appName: 'Auto Rental Manager',
  appShortName: 'ARMS',

  nav: {
    main: 'Main',
    openMenu: 'Open menu',
    closeMenu: 'Close menu',
    groups: {
      overview: 'Overview',
      drivers: 'Drivers',
      fleet: 'Autos and agreements',
      money: 'Money',
      admin: 'Administration',
    },
  },

  pages: {
    signIn: 'Sign in',
    ownerDashboard: 'Owner dashboard',
    staffDashboard: 'Staff dashboard',
    drivers: 'Drivers',
    driver: 'Driver',
    registerDriver: 'Register driver',
    kycQueue: 'KYC queue',
    autos: 'Autos',
    agreements: 'Agreements',
    payRequests: 'Pay requests today',
    payments: 'Payments',
    bankStatements: 'Bank statements',
    escalations: 'Escalations',
    reports: 'Reports',
    staff: 'Staff',
    settings: 'Settings',
    auditLog: 'Audit log',
    notFound: 'Page not found',
  },

  placeholder: {
    comingIn: (week: number) => `Coming in Week ${week}`,
    body: 'This screen is part of a later milestone. Nothing here works yet.',
  },

  notFound: {
    body: 'There is no page at this address.',
    home: 'Go to the dashboard',
  },

  apiStatus: {
    online: 'API online',
    offline: 'API offline',
    checking: 'Checking API…',
  },

  common: {
    loading: 'Loading…',
    close: 'Close',
    tryAgain: 'Try again',
    somethingWentWrong: 'Something went wrong.',
    requestId: (id: string) => `Request id: ${id}`,
    nothingHereYet: 'Nothing here yet.',
  },

  pagination: {
    label: 'Pagination',
    previous: 'Previous page',
    next: 'Next page',
    showing: (from: number, to: number, total: number) => `Showing ${from}–${to} of ${total}`,
    none: 'No results',
  },
} as const;
