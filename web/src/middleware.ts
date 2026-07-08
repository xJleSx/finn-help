import { NextResponse, type NextRequest } from "next/server";
import { decodeJwt } from "jose";

const protectedPaths = ["/dashboard", "/alerts", "/instruments", "/portfolio", "/profile", "/paper"];
const authPaths = ["/login", "/register"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const authCookie = request.cookies.get("finn_auth_token")?.value;

  let isValid = false;
  if (authCookie) {
    try {
      const payload = decodeJwt(authCookie);
      if (payload.exp) {
        isValid = Date.now() < payload.exp * 1000;
      } else {
        isValid = true;
      }
    } catch {
      isValid = false;
    }
  }

  const isProtected = protectedPaths.some((p) => pathname.startsWith(p));
  const isAuthPage = authPaths.some((p) => pathname.startsWith(p));

  if (isProtected && !isValid) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("redirect", pathname);
    return NextResponse.redirect(loginUrl);
  }

  if (isAuthPage && isValid) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api/).*)"],
};
