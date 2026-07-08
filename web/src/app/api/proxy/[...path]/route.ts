import { NextRequest, NextResponse } from "next/server";

const API_BACKEND = process.env.API_URL || "http://127.0.0.1:8000";

export async function GET(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  return proxyRequest(request, params, "GET");
}

export async function POST(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  return proxyRequest(request, params, "POST");
}

export async function PUT(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  return proxyRequest(request, params, "PUT");
}

export async function DELETE(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  return proxyRequest(request, params, "DELETE");
}

async function proxyRequest(request: NextRequest, paramsPromise: Promise<{ path: string[] }>, method: string) {
  const { path } = await paramsPromise;
  const authToken = request.cookies.get("finn_auth_token")?.value;
  const backendPath = `/api/${path.join("/")}` + request.nextUrl.search;

  const headers: Record<string, string> = {};
  if (authToken) {
    headers["Authorization"] = `Bearer ${authToken}`;
  }

  let body: BodyInit | undefined;
  const contentType = request.headers.get("content-type");
  if (contentType?.includes("application/json") && method !== "GET") {
    body = await request.text();
    headers["Content-Type"] = "application/json";
  }

  try {
    const res = await fetch(`${API_BACKEND}${backendPath}`, {
      method,
      headers,
      body,
    });

    const responseHeaders: Record<string, string> = {};
    res.headers.forEach((value, key) => {
      if (!["content-encoding", "content-length", "transfer-encoding", "connection"].includes(key)) {
        responseHeaders[key] = value;
      }
    });

    const text = await res.text();
    return new NextResponse(text, {
      status: res.status,
      headers: responseHeaders,
    });
  } catch {
    return NextResponse.json({ error: "Backend unreachable" }, { status: 502 });
  }
}
