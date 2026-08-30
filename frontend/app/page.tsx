import AnalyticsPage from "./analytics-page";
import MaintenancePage from "./maintenance-page";
import { selectHomeSurface } from "./runtime-policy";

export default function HomePage() {
  return selectHomeSurface(process.env.NODE_ENV) === "analytics"
    ? <AnalyticsPage />
    : <MaintenancePage />;
}
