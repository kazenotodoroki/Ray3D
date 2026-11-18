package ch.ray3d.telemetre

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Bundle
import android.os.VibrationEffect
import android.os.Vibrator
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import org.json.JSONArray
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.SocketTimeoutException
import kotlin.concurrent.thread

/**
 * Coquille WebView du télémètre Ray 3D.
 * - start.html (dans l'APK) : recherche du serveur Ray 3D sur le Wi-Fi (diffusion UDP) ou saisie
 *   de son adresse ;
 * - puis charge http://<serveur>/app, la page servie par Ray 3D (toujours à jour avec l'ordinateur).
 */
class MainActivity : Activity() {

    private lateinit var web: WebView
    private val prefs by lazy { getSharedPreferences("ray3d", Context.MODE_PRIVATE) }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        web = WebView(this)
        web.setBackgroundColor(0xFF0C0E11.toInt())
        setContentView(web)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = true
        }
        web.webViewClient = object : WebViewClient() {
            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                if (request.isForMainFrame) goHome("Serveur injoignable : " + request.url.host)
            }
        }
        web.addJavascriptInterface(Bridge(), "Ray3DAndroid")
        if (savedInstanceState != null) web.restoreState(savedInstanceState)
        else goHome(null)
    }

    private fun goHome(msg: String?) {
        val q = if (msg != null) "?msg=" + android.net.Uri.encode(msg) else ""
        web.loadUrl("file:///android_asset/start.html$q")
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (web.url?.startsWith("http") == true) goHome(null) else super.onBackPressed()
    }

    /** Adresse de diffusion du réseau Wi-Fi (ex. 192.168.1.255), en plus de 255.255.255.255. */
    private fun broadcastAddresses(): List<InetAddress> {
        val out = mutableListOf(InetAddress.getByName("255.255.255.255"))
        try {
            val wifi = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            @Suppress("DEPRECATION") val dhcp = wifi.dhcpInfo
            if (dhcp != null && dhcp.ipAddress != 0) {
                val bc = (dhcp.ipAddress and dhcp.netmask) or dhcp.netmask.inv()
                val b = ByteArray(4) { k -> (bc shr (k * 8) and 0xFF).toByte() }
                out.add(InetAddress.getByAddress(b))
            }
        } catch (_: Exception) {
        }
        return out
    }

    inner class Bridge {
        /** Lance la recherche ; le résultat arrive dans window.onServers(liste). */
        @JavascriptInterface
        fun discover() {
            thread {
                val found = JSONArray()
                val seen = HashSet<String>()
                try {
                    DatagramSocket().use { s ->
                        s.broadcast = true
                        s.soTimeout = 400
                        val msg = "RAY3D?".toByteArray()
                        val until = System.currentTimeMillis() + 1800
                        var next = 0L
                        val buf = ByteArray(512)
                        while (System.currentTimeMillis() < until) {
                            if (System.currentTimeMillis() >= next) {
                                for (a in broadcastAddresses()) {
                                    try { s.send(DatagramPacket(msg, msg.size, a, 47800)) } catch (_: Exception) {}
                                }
                                next = System.currentTimeMillis() + 600
                            }
                            try {
                                val p = DatagramPacket(buf, buf.size)
                                s.receive(p)
                                val j = JSONObject(String(p.data, 0, p.length))
                                val addr = p.address.hostAddress + ":" + j.optInt("port", 8765)
                                if (j.optString("app") == "ray3d" && seen.add(addr)) {
                                    found.put(JSONObject().put("addr", addr).put("name", j.optString("name")))
                                }
                            } catch (_: SocketTimeoutException) {
                            } catch (_: Exception) {
                            }
                        }
                    }
                } catch (_: Exception) {
                }
                runOnUiThread { web.evaluateJavascript("window.onServers && onServers($found)", null) }
            }
        }

        @JavascriptInterface
        fun lastServer(): String = prefs.getString("server", "") ?: ""

        /** Ouvre la page du télémètre servie par Ray 3D. */
        @JavascriptInterface
        fun open(addr: String) {
            val a = addr.trim().removePrefix("http://").trimEnd('/')
            prefs.edit().putString("server", a).apply()
            runOnUiThread { web.loadUrl("http://$a/app") }
        }

        @JavascriptInterface
        fun home() {
            runOnUiThread { goHome(null) }
        }

        @JavascriptInterface
        fun vibrate(ms: Int) {
            val v = getSystemService(Vibrator::class.java) ?: return
            if (Build.VERSION.SDK_INT >= 26) v.vibrate(VibrationEffect.createOneShot(ms.toLong(), VibrationEffect.DEFAULT_AMPLITUDE))
        }
    }
}
