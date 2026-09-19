import './globals.css';
import './workbench.css';
import AppThemeProvider from '../components/AppThemeProvider';

export const metadata = {
  title: 'Appian Sentinel',
  description: 'Appian development workbench for desktop',
  icons: { icon: '/icon.png' },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" data-theme="dark">
      <body>
        <AppThemeProvider>{children}</AppThemeProvider>
      </body>
    </html>
  );
}
