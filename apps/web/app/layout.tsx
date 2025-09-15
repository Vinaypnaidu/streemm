// import "./globals.css";

// export const metadata = { title: "Reelay" };

// export default function RootLayout({ children }: { children: React.ReactNode }) {
//   return (
//     <html lang="en">
//       <body className="min-h-screen bg-neutral-900 text-neutral-100 antialiased">
//         {children}
//       </body>
//     </html>
//   );
// }

import "./globals.css";

export const metadata = { title: "Reelay" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-white text-neutral-900 antialiased">
        {children}
      </body>
    </html>
  );
}