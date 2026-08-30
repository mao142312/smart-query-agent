export type HomeSurface = "analytics" | "maintenance";

export function selectHomeSurface(environment: string | undefined): HomeSurface {
  return environment === "development" ? "analytics" : "maintenance";
}
