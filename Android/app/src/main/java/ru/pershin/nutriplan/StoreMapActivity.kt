package ru.pershin.nutriplan

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.View
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.*
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import org.json.JSONArray
import org.json.JSONObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.util.Locale
import kotlin.math.ceil

class StoreMapActivity : AppCompatActivity() {
    private lateinit var map: WebView
    private lateinit var status: TextView
    private lateinit var selectedText: TextView
    private lateinit var routeText: TextView
    private lateinit var routeButton: Button
    private lateinit var locationButton: Button
    private lateinit var chooseButton: Button
    private lateinit var progress: ProgressBar
    private lateinit var chainSpinner: Spinner
    private lateinit var radiusSpinner: Spinner
    private lateinit var storeList: LinearLayout
    private lateinit var locationManager: LocationManager
    private val handler = Handler(Looper.getMainLooper())
    private var listener: LocationListener? = null
    private var position: Pair<Double, Double>? = null
    private var stores = emptyList<NearbyStore>()
    private var selected: NearbyStore? = null
    private var mapReady = false
    private var revision = 0
    private var storesCall: Call<StoreLocationsResponse>? = null
    private var routeCall: Call<WalkingRouteResponse>? = null
    private var routePoints = emptyList<List<Double>>()
    private val chains = listOf("Все сети", "Верный", "Пятёрочка", "Магнит")
    private val radii = listOf(1.0, 3.0, 5.0)
    private val permission = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        if (hasLocationPermission()) locate() else {
            busy(false)
            status.text = "Геолокация не разрешена. Можно выбрать точку на карте вручную."
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_store_map)
        map = findViewById(R.id.storeMapWebView)
        status = findViewById(R.id.mapStatus)
        selectedText = findViewById(R.id.mapSelectedStore)
        routeText = findViewById(R.id.mapRouteResult)
        routeButton = findViewById(R.id.mapRouteButton)
        locationButton = findViewById(R.id.mapLocationButton)
        chooseButton = findViewById(R.id.mapChoosePointButton)
        progress = findViewById(R.id.mapProgress)
        chainSpinner = findViewById(R.id.mapChainSpinner)
        radiusSpinner = findViewById(R.id.mapRadiusSpinner)
        storeList = findViewById(R.id.mapStoreList)
        locationManager = getSystemService(Context.LOCATION_SERVICE) as LocationManager
        chainSpinner.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, chains)
        radiusSpinner.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, listOf("1 км", "3 км", "5 км"))
        radiusSpinner.setSelection(1)
        locationButton.setOnClickListener {
            busy(true)
            if (hasLocationPermission()) locate() else permission.launch(arrayOf(
                Manifest.permission.ACCESS_COARSE_LOCATION, Manifest.permission.ACCESS_FINE_LOCATION))
        }
        chooseButton.setOnClickListener {
            if (mapReady) {
                status.text = "Нажмите на карту в точке, откуда пойдёте за продуктами."
                map.evaluateJavascript("window.choosePosition();", null)
            }
        }
        routeButton.setOnClickListener { requestRoute() }
        findViewById<Button>(R.id.mapProductSearchButton).setOnClickListener {
            startActivity(Intent(this, StorePricesActivity::class.java)
                .putExtra("week_index", intent.getIntExtra("week_index", 0)))
        }
        chainSpinner.onItemSelectedListener = selectionListener { renderStores() }
        radiusSpinner.onItemSelectedListener = selectionListener { if (position != null) searchStores() }
        map.settings.apply {
            javaScriptEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW
            userAgentString = "$userAgentString NutriPlan-VKR/1.0"
            cacheMode = android.webkit.WebSettings.LOAD_DEFAULT
        }
        // Only bundled JavaScript runs here; tokens and profile data never enter the map.
        map.webViewClient = object : WebViewClient() {
            override fun onPageCommitVisible(view: WebView, url: String) {
                enableMapControls(view)
            }
            override fun onPageFinished(view: WebView, url: String) {
                enableMapControls(view)
            }
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val uri = request.url
                if (uri.scheme == "nutriplan-map") {
                    when (uri.host) {
                        "store" -> stores.firstOrNull { it.id == uri.getQueryParameter("id") }?.let { selectStore(it) }
                        "position" -> {
                            val lat = uri.getQueryParameter("lat")?.toDoubleOrNull()
                            val lon = uri.getQueryParameter("lon")?.toDoubleOrNull()
                            if (lat != null && lon != null && lat.isFinite() && lon.isFinite() && lat in -90.0..90.0 && lon in -180.0..180.0) {
                                stopLocationUpdates()
                                setPosition(lat, lon, "Выбранная точка")
                            }
                        }
                    }
                } else if (uri.scheme == "https" && uri.host in listOf("www.openstreetmap.org", "leafletjs.com", "routing.openstreetmap.de")) {
                    runCatching { startActivity(Intent(Intent.ACTION_VIEW, uri)) }
                }
                return true
            }
        }
        chooseButton.isEnabled = false
        val template = assets.open("store-map.html").bufferedReader().use { it.readText() }
        val css = assets.open("leaflet/leaflet.css").bufferedReader().use { it.readText() }
        val js = assets.open("leaflet/leaflet.js").bufferedReader().use { it.readText() }
        map.loadDataWithBaseURL("https://nutriplan.invalid/", template.replace("/*LEAFLET_CSS*/", css).replace("/*LEAFLET_JS*/", js), "text/html", "UTF-8", null)
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.main)) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }
        if (savedInstanceState?.containsKey("latitude") == true) {
            setPosition(savedInstanceState.getDouble("latitude"), savedInstanceState.getDouble("longitude"), "Выбранная точка")
        }
    }

    private fun enableMapControls(view: WebView) {
        view.evaluateJavascript("typeof window.renderStores === 'function'") { ready ->
            if (ready == "true" && !isDestroyed) {
                mapReady = true
                chooseButton.isEnabled = progress.visibility != View.VISIBLE
                renderMap()
            }
        }
    }

    private fun selectionListener(action: () -> Unit) = object : AdapterView.OnItemSelectedListener {
        override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) = action()
        override fun onNothingSelected(parent: AdapterView<*>?) = Unit
    }

    private fun hasLocationPermission() = listOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)
        .any { ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED }

    @SuppressLint("MissingPermission")
    private fun locate() {
        stopLocationUpdates()
        val cached = locationManager.getProviders(true).mapNotNull {
            runCatching { locationManager.getLastKnownLocation(it) }.getOrNull()
        }.filter { SystemClock.elapsedRealtimeNanos() - it.elapsedRealtimeNanos in 0L..600_000_000_000L }
            .maxByOrNull { it.time }
        if (cached != null) { setPosition(cached.latitude, cached.longitude, "Ваше местоположение"); return }
        val provider = when {
            locationManager.isProviderEnabled(LocationManager.NETWORK_PROVIDER) -> LocationManager.NETWORK_PROVIDER
            ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED &&
                locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER) -> LocationManager.GPS_PROVIDER
            else -> null
        }
        if (provider == null) { busy(false); status.text = "Включите геолокацию или выберите точку вручную."; return }
        val update = object : LocationListener {
            override fun onLocationChanged(location: Location) {
                stopLocationUpdates()
                setPosition(location.latitude, location.longitude, "Ваше местоположение")
            }
        }
        listener = update
        try { locationManager.requestLocationUpdates(provider, 0L, 0f, update, Looper.getMainLooper()) }
        catch (error: SecurityException) { stopLocationUpdates(); busy(false); status.text = "Разрешение изменилось. Выберите точку или повторите геолокацию."; return }
        handler.postDelayed({ if (listener === update) {
            stopLocationUpdates(); busy(false); status.text = "Местоположение не получено. Можно выбрать точку на карте."
        } }, 15_000)
    }

    private fun stopLocationUpdates() {
        listener?.let { runCatching { locationManager.removeUpdates(it) } }
        listener = null
        handler.removeCallbacksAndMessages(null)
    }

    private fun setPosition(lat: Double, lon: Double, label: String) {
        position = lat to lon
        status.text = label
        searchStores()
    }

    private fun token(): String? = getSharedPreferences("nutriplan_session", MODE_PRIVATE).getString("access_token", null)
    private fun region() = intent.getIntExtra("region_id", getSharedPreferences("store_search", MODE_PRIVATE).getInt("region", 1))

    private fun searchStores() {
        val point = position ?: return
        val auth = token()
        if (auth == null) { busy(false); status.text = "Для поиска магазинов выполните вход в приложение."; renderMap(); return }
        revision++
        val current = revision
        storesCall?.cancel()
        clearRoute()
        stores = emptyList()
        renderStores()
        busy(true)
        status.text = "Ищем продуктовые магазины рядом с выбранной точкой…"
        ApiClient.service.nearbyStores("Bearer $auth", StoreLocationsRequest(point.first, point.second, radii[radiusSpinner.selectedItemPosition], region()))
            .also { storesCall = it }.enqueue(object : Callback<StoreLocationsResponse> {
                override fun onResponse(call: Call<StoreLocationsResponse>, response: Response<StoreLocationsResponse>) {
                    if (current != revision) return
                    busy(false)
                    val data = response.body()
                    if (!response.isSuccessful || data == null) {
                        status.text = errorText(response.code()); return
                    }
                    stores = data.stores
                    status.text = when (data.status) {
                        "unavailable" -> "Источники адресов недоступны. Повторите поиск позже."
                        "partial" -> "Часть источников адресов недоступна; показаны полученные магазины."
                        else -> "Найдено ${stores.size} магазинов. Расстояние в списке — по прямой."
                    }
                    data.sources.firstOrNull { it.partial }?.let {
                        status.text = "Источник перегружен: адреса OpenStreetMap получены только в радиусе ${it.coverageRadiusKm} км. Список может быть неполным."
                    }
                    renderStores()
                }
                override fun onFailure(call: Call<StoreLocationsResponse>, error: Throwable) {
                    if (call.isCanceled || current != revision) return
                    busy(false); status.text = "Нет связи с сервером. Повторите поиск местоположения или точки."
                }
            })
    }

    private fun filteredStores() = stores.filter { chainSpinner.selectedItemPosition == 0 || it.chain == chains[chainSpinner.selectedItemPosition] }

    private fun renderStores() {
        val visible = filteredStores()
        if (selected?.id !in visible.map { it.id }) clearRoute()
        storeList.removeAllViews()
        visible.forEach { store -> storeList.addView(Button(this).apply {
            isAllCaps = false
            text = "${store.chain}\n${distance(store.distanceMeters)} по прямой"
            setOnClickListener { selectStore(store) }
        }) }
        if (visible.isEmpty() && stores.isNotEmpty()) selectedText.text = "В выбранном радиусе магазинов этой сети не найдено."
        if (visible.isEmpty() && position != null && stores.isEmpty()) selectedText.text = "Магазины пока не найдены. Можно увеличить радиус или выбрать другую точку."
        renderMap()
    }

    private fun selectStore(store: NearbyStore) {
        clearRoute()
        selected = store
        selectedText.text = "${store.chain}: ${store.address}\n${distance(store.distanceMeters)} по прямой" +
            (store.openingHours?.let { "\nЧасы работы: $it" } ?: "")
        routeButton.isEnabled = position != null
        renderMap()
    }

    private fun clearRoute() {
        routeCall?.cancel()
        selected = null
        routePoints = emptyList()
        routeText.text = ""
        selectedText.text = "Выберите магазин на карте или в списке."
        routeButton.isEnabled = false
    }

    private fun requestRoute() {
        val store = selected ?: return
        val point = position ?: return
        val auth = token() ?: return
        routeCall?.cancel()
        routePoints = emptyList()
        renderMap()
        routeButton.isEnabled = false
        routeText.text = "Строим пеший маршрут…"
        ApiClient.service.walkingRoute("Bearer $auth", WalkingRouteRequest(point.first, point.second, store.latitude, store.longitude))
            .also { routeCall = it }.enqueue(object : Callback<WalkingRouteResponse> {
                override fun onResponse(call: Call<WalkingRouteResponse>, response: Response<WalkingRouteResponse>) {
                    if (call.isCanceled || selected?.id != store.id || position != point) return
                    routeButton.isEnabled = true
                    val data = response.body()
                    if (!response.isSuccessful || data == null) { routeText.text = errorText(response.code()); return }
                    if (!data.available || data.distanceMeters == null || data.durationSeconds == null) {
                        routeText.text = data.message; return
                    }
                    routePoints = data.geometry
                    val minutes = ceil(data.durationSeconds / 60.0).toInt().coerceAtLeast(1)
                    routeText.text = "Пешком: ${distance(data.distanceMeters)} · около $minutes мин\nВремя без остановок и закупки продуктов."
                    renderMap()
                }
                override fun onFailure(call: Call<WalkingRouteResponse>, error: Throwable) {
                    if (call.isCanceled || selected?.id != store.id || position != point) return
                    routeButton.isEnabled = true
                    routeText.text = "Маршрут недоступен. Время в пути не рассчитано."
                }
            })
    }

    private fun renderMap() {
        if (!mapReady) return
        val data = JSONObject()
        position?.let { data.put("position", JSONArray(listOf(it.first, it.second))) }
        data.put("selected", selected?.id ?: JSONObject.NULL)
        data.put("route", JSONArray(routePoints.map { JSONArray(it) }))
        data.put("stores", JSONArray(filteredStores().map { store -> JSONObject()
            .put("id", store.id).put("chain", store.chain).put("address", store.address)
            .put("latitude", store.latitude).put("longitude", store.longitude)
            .put("distance", distance(store.distanceMeters)) }))
        map.evaluateJavascript("window.renderStores($data);", null)
    }

    private fun distance(meters: Int) = if (meters < 1000) "$meters м" else String.format(Locale.getDefault(), "%.1f км", meters / 1000.0)
    private fun errorText(code: Int) = when (code) {
        404 -> "На сервере ещё не установлен модуль карты и маршрутов."
        401, 403 -> "Сессия истекла. Выполните вход заново."
        422 -> "Проверьте выбранную точку, регион и расстояние до магазина."
        else -> "Поиск недоступен. Код: $code"
    }
    private fun busy(value: Boolean) {
        progress.visibility = if (value) View.VISIBLE else View.GONE
        locationButton.isEnabled = !value
        radiusSpinner.isEnabled = !value
        chooseButton.isEnabled = mapReady && !value
    }
    override fun onSaveInstanceState(outState: Bundle) {
        position?.let { outState.putDouble("latitude", it.first); outState.putDouble("longitude", it.second) }
        super.onSaveInstanceState(outState)
    }
    override fun onDestroy() {
        revision++
        storesCall?.cancel(); routeCall?.cancel(); stopLocationUpdates()
        map.stopLoading(); map.destroy()
        super.onDestroy()
    }
}
