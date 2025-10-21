// apps/web/app/layout.tsx
import "./globals.css";
import Navbar from "./components/Navbar";
import { AuthProvider } from "./providers";
import AuthGate from "./components/AuthGate";

export const metadata = { title: "Streem" };

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-neutral-950 text-neutral-100 antialiased">
        <AuthProvider>
          <AuthGate>
            <Navbar />
            <main className="min-h-[calc(100vh-56px)] md:pl-56">
              {children}
            </main>
          </AuthGate>
        </AuthProvider>
      </body>
    </html>
  );
}
