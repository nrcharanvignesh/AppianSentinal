import { Open_Sans } from 'next/font/google';

import './globals.css';
import './workbench.css';
import AppThemeProvider from '../components/AppThemeProvider';

// Open Sans is Appian's standard web typeface. next/font self-hosts it at
// build time, so the installed app needs no network to render correctly.
const openSans = Open_Sans({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-appian',
});

export const metadata = {
  title: 'Appian Sentinel',
  description: 'Appian development workbench for desktop',
  icons: { icon: '/icon.png' },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" data-theme="dark" className={openSans.variable}>
      <body>
        <AppThemeProvider>{children}</AppThemeProvider>
      </body>
    </html>
  );
}
