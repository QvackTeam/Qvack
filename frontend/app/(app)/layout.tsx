import { AppShell } from "@/components/quack/app-shell";
import { Preloader } from "@/components/quack/preloader";
import { DataProvider } from "@/lib/api/data";

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <DataProvider>
      <AppShell>{children}</AppShell>
      <Preloader />
    </DataProvider>
  );
}
