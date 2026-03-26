import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Fleet Dashboard',
  description: 'Claude Fleet Management Dashboard',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-[#0c0c0f] text-zinc-200 antialiased">
        {children}
      </body>
    </html>
  );
}
