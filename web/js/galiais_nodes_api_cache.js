import { api } from "../../scripts/api.js";

export function apiUrl(path) {
    if (api?.apiURL) return api.apiURL(path);
    return path;
}

export function cacheKey(parts) {
    return JSON.stringify(parts.map((part) => String(part ?? "")));
}

export function createLruCache(limit = 100) {
    const cache = new Map();
    const safeLimit = Math.max(1, Number(limit || 100));
    return {
        has(key) {
            return cache.has(key);
        },
        get(key) {
            if (!cache.has(key)) return null;
            const value = cache.get(key);
            cache.delete(key);
            cache.set(key, value);
            return value;
        },
        set(key, value) {
            cache.set(key, value);
            while (cache.size > safeLimit) {
                const oldest = cache.keys().next().value;
                cache.delete(oldest);
            }
        },
        clear() {
            cache.clear();
        },
        get size() {
            return cache.size;
        },
    };
}

export async function readJsonResponse(response, fallbackMessage = "请求失败") {
    const text = await response.text();
    let payload = null;
    if (text.trim()) {
        try {
            payload = JSON.parse(text);
        } catch (error) {
            const preview = text.replace(/\s+/g, " ").slice(0, 180);
            throw new Error(`${fallbackMessage}: 后端未返回JSON (${response.status} ${response.statusText}) ${preview}`);
        }
    }
    if (!response.ok) {
        const message = payload?.error || payload?.message || response.statusText || fallbackMessage;
        throw new Error(`${fallbackMessage}: ${message}`);
    }
    if (!payload) {
        throw new Error(`${fallbackMessage}: 后端返回空响应，请重启ComfyUI并刷新页面`);
    }
    return payload;
}
