package ru.pershin.nutriplan

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.net.Uri
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Spinner
import android.widget.ArrayAdapter
import android.widget.CheckBox
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.util.Locale

class StorePricesActivity : AppCompatActivity() {
    private lateinit var productInput: EditText
    private lateinit var compareButton: Button
    private lateinit var progress: ProgressBar
    private lateinit var result: TextView
    private lateinit var regionSpinner: Spinner
    private lateinit var planProductsButton: Button
    private lateinit var magnitLink: EditText
    private lateinit var refreshPrices: CheckBox
    private lateinit var locationManager: LocationManager
    private var pendingProduct = ""
    private var locationListener: LocationListener? = null
    private val handler = Handler(Looper.getMainLooper())
    private val regions = listOf(1 to "Москва и область", 2 to "Екатеринбург и область",
        4 to "Тула и область", 5 to "Казань и Татарстан", 6 to "Санкт-Петербург и область",
        7 to "Владимир и область", 8 to "Великий Новгород и область", 9 to "Ярославль и область",
        10 to "Калуга и область", 12 to "Тверь и область")
    private var searchCall: Call<StoreComparisonResponse>? = null
    private var planCall: Call<PlanProductsResponse>? = null

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        if (permissions[Manifest.permission.ACCESS_FINE_LOCATION] == true ||
            permissions[Manifest.permission.ACCESS_COARSE_LOCATION] == true
        ) {
            locateAndCompare()
        } else {
            showLoading(false)
            result.text = "Без разрешения на геолокацию нельзя определить ближайшие магазины."
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_store_prices)
        productInput = findViewById(R.id.storeProductInput)
        compareButton = findViewById(R.id.compareStorePricesButton)
        progress = findViewById(R.id.storePricesProgress)
        result = findViewById(R.id.storePricesResult)
        regionSpinner = findViewById(R.id.storeRegionSpinner)
        planProductsButton = findViewById(R.id.findPlanProductsButton)
        magnitLink = findViewById(R.id.magnitStoreLinkInput)
        refreshPrices = findViewById(R.id.refreshStorePricesCheckBox)
        magnitLink.setText(getSharedPreferences("store_search", MODE_PRIVATE).getString("magnit_link", ""))
        findViewById<Button>(R.id.openMagnitWebsiteButton).setOnClickListener {
            runCatching { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://magnit.ru/"))) }
        }
        regionSpinner.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item,
            regions.map { it.second })
        val savedRegion = getSharedPreferences("store_search", MODE_PRIVATE).getInt("region", 1)
        regionSpinner.setSelection(regions.indexOfFirst { it.first == savedRegion }.coerceAtLeast(0))
        val week = intent.getIntExtra("week_index", 0)
        planProductsButton.text = "Подобрать товары с ИИ: неделя ${week + 1}"
        planProductsButton.setOnClickListener { findPlanProducts(week) }
        findViewById<Button>(R.id.openStoreMapButton).setOnClickListener {
            startActivity(Intent(this, StoreMapActivity::class.java)
                .putExtra("region_id", selectedRegion()).putExtra("week_index", week))
        }
        locationManager = getSystemService(Context.LOCATION_SERVICE) as LocationManager

        compareButton.setOnClickListener {
            if (!validMagnitLink()) return@setOnClickListener
            pendingProduct = productInput.text.toString().trim()
            if (pendingProduct.length < 2) {
                productInput.error = "Введите название продукта"
            } else {
                showLoading(true)
                ensureLocationPermission()
            }
        }
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.main)) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }
    }

    private fun ensureLocationPermission() {
        val fine = ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
        val coarse = ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_COARSE_LOCATION)
        if (fine == PackageManager.PERMISSION_GRANTED || coarse == PackageManager.PERMISSION_GRANTED) {
            locateAndCompare()
        } else {
            permissionLauncher.launch(arrayOf(
                Manifest.permission.ACCESS_FINE_LOCATION,
                Manifest.permission.ACCESS_COARSE_LOCATION
            ))
        }
    }

    @SuppressLint("MissingPermission")
    private fun locateAndCompare() {
        val available = locationManager.getProviders(true)
        val cached = available.mapNotNull { provider ->
            runCatching { locationManager.getLastKnownLocation(provider) }.getOrNull()
        }.maxByOrNull { it.time }
        if (cached != null && SystemClock.elapsedRealtimeNanos() - cached.elapsedRealtimeNanos in 0L..(10L * 60 * 1_000_000_000)) {
            requestComparison(cached)
            return
        }
        val provider = when {
            locationManager.isProviderEnabled(LocationManager.NETWORK_PROVIDER) -> LocationManager.NETWORK_PROVIDER
            ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED &&
                locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER) -> LocationManager.GPS_PROVIDER
            else -> null
        }
        if (provider == null) {
            showLoading(false)
            result.text = "Включите геолокацию на телефоне и повторите поиск."
            return
        }
        val listener = object : LocationListener {
            override fun onLocationChanged(location: Location) {
                locationManager.removeUpdates(this)
                locationListener = null
                requestComparison(location)
            }
            override fun onProviderEnabled(provider: String) = Unit
            override fun onProviderDisabled(provider: String) = Unit
            @Deprecated("Deprecated in Android")
            override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) = Unit
        }
        locationListener = listener
        try {
            locationManager.requestLocationUpdates(provider, 0L, 0f, listener, Looper.getMainLooper())
        } catch (error: SecurityException) {
            locationListener = null
            showLoading(false)
            result.text = "Разрешение на геолокацию изменилось. Повторите поиск."
            return
        }
        handler.postDelayed({
            if (locationListener === listener) {
                locationManager.removeUpdates(listener)
                locationListener = null
                showLoading(false)
                result.text = "Не удалось определить местоположение. Выйдите на открытое место и повторите поиск."
            }
        }, 15_000)
    }

    private fun requestComparison(location: Location) {
        val token = getSharedPreferences("nutriplan_session", MODE_PRIVATE)
            .getString("access_token", null)
        if (token == null) {
            showLoading(false)
            result.text = "Сессия истекла. Выполните вход заново."
            return
        }
        ApiClient.service.compareStorePrices(
            "Bearer $token",
            StoreComparisonRequest(location.latitude, location.longitude, 5.0, pendingProduct, selectedRegion(), magnitShopCode(), refreshPrices.isChecked)
        ).also { searchCall = it }.enqueue(object : Callback<StoreComparisonResponse> {
            override fun onResponse(call: Call<StoreComparisonResponse>, response: Response<StoreComparisonResponse>) {
                showLoading(false)
                val data = response.body()
                if (!response.isSuccessful || data == null) {
                    result.text = requestError(response.code())
                    return
                }
                result.text = render(data)
            }

            override fun onFailure(call: Call<StoreComparisonResponse>, error: Throwable) {
                if (call.isCanceled) return
                showLoading(false)
                result.text = "Нет связи с сервером. Проверьте интернет и повторите попытку."
            }
        })
    }

    private fun render(data: StoreComparisonResponse): String {
        val stores = if (data.stores.isEmpty()) {
            "В радиусе 5 км магазины выбранных сетей не найдены."
        } else data.stores.take(8).joinToString("\n") {
            "• ${it.chain}: ${it.address} — ${formatDistance(it.distanceMeters)}"
        }
        val offers = if (data.offers.isEmpty()) {
            "Подтверждённых предложений в открытых каталогах нет."
        } else data.offers.joinToString("\n\n") { offerText(it) }
        val sources = data.sources.joinToString("\n") {
            "• ${it.chain}: ${it.message}" + (it.fetchedAt?.let { date -> "\nПолучено: $date" } ?: "")
        }
        return "Регион каталога: ${data.region.orEmpty()}\n\nБлижайшие магазины\n$stores\n\nЦены на «${data.searchedProduct}»\n$offers" +
            (if (sources.isBlank()) "" else "\n\nСтатус источников\n$sources") +
            (if (data.locationStatus == "osm_unavailable") "\n\nАдреса остальных сетей сейчас недоступны." else "") +
            "\n\n${data.disclaimer}"
    }

    private fun selectedRegion(): Int = regions[regionSpinner.selectedItemPosition].first.also {
        getSharedPreferences("store_search", MODE_PRIVATE).edit().putInt("region", it).apply()
    }

    private fun offerText(offer: StorePriceOffer): String {
        val price = String.format(Locale.getDefault(), "%.2f", offer.price)
        val unit = if (offer.packageUnit == "ml") "л" else "кг"
        val comparable = offer.pricePerUnit?.let {
            "\n${String.format(Locale.getDefault(), "%.2f", it)} ₽/$unit"
        }.orEmpty()
        val dates = if (offer.validFrom != null && offer.validUntil != null)
            "\nАкция: ${offer.validFrom} — ${offer.validUntil}" else "\nСрок действия цены не указан"
        return "${offer.chain}: ${offer.product}\n$price ₽$comparable" +
            (offer.`package`?.let { "\nКоличество за указанную цену: $it" } ?: "") + dates +
            (offer.storeAddress?.let { "\nВитрина доставки: $it" } ?: "") +
            (offer.fetchedAt?.let { "\nПолучено: $it" } ?: "") +
            "\n${offer.conditions.orEmpty()}\n${offer.sourceUrl}"
    }

    private fun magnitShopCode(): String? = Uri.parse(magnitLink.text.toString().trim()).getQueryParameter("shopCode")

    private fun validMagnitLink(): Boolean {
        val text = magnitLink.text.toString().trim()
        if (text.isNotEmpty()) {
            val uri = runCatching { Uri.parse(text) }.getOrNull()
            val code = runCatching { uri?.getQueryParameter("shopCode") }.getOrNull()
            if (uri?.scheme != "https" || uri.host != "magnit.ru" ||
                code?.matches(Regex("[0-9]{4,20}")) != true || uri.getQueryParameter("shopType") != "dostavka") {
                magnitLink.error = "Откройте товар после выбора адреса доставки на magnit.ru и скопируйте полную ссылку"
                return false
            }
        }
        getSharedPreferences("store_search", MODE_PRIVATE).edit().putString("magnit_link", text).apply()
        return true
    }

    private fun requestError(code: Int): String = when (code) {
        404 -> "На сервере ещё не установлен модуль поиска товаров."
        400 -> "Сначала сформируйте рацион."
        401, 403 -> "Сессия истекла. Выполните вход заново."
        422 -> "Проверьте регион и выбранную неделю. Для старого плана сформируйте рацион заново."
        else -> "Поиск сейчас недоступен. Код: $code"
    }

    private fun findPlanProducts(week: Int) {
        if (!validMagnitLink()) return
        val token = getSharedPreferences("nutriplan_session", MODE_PRIVATE).getString("access_token", null)
        if (token == null) {
            result.text = "Выполните вход заново."
            return
        }
        showLoading(true)
        result.text = "Ищем товары для недели и передаём найденные варианты домашней нейросети…"
        ApiClient.service.findPlanProducts("Bearer $token", PlanProductsRequest(selectedRegion(), week, magnitShopCode(), refreshPrices.isChecked))
            .also { planCall = it }.enqueue(object : Callback<PlanProductsResponse> {
                override fun onResponse(call: Call<PlanProductsResponse>, response: Response<PlanProductsResponse>) {
                    showLoading(false)
                    val data = response.body()
                    if (!response.isSuccessful || data == null) {
                        result.text = requestError(response.code())
                        return
                    }
                    val status = when (data.aiStatus) {
                        "ok" -> "ИИ предложил товары из найденного каталога."
                        "no_candidates" -> "Для списка покупок подходящих предложений не найдено."
                        "invalid_response" -> "Ответ ИИ не прошёл проверку. Ниже найденные варианты."
                        else -> "Домашняя нейросеть недоступна. Ниже найденные варианты."
                    }
                    val rows = data.items.joinToString("\n\n") { item ->
                        val choice = item.offer?.let { offerText(it) + "\n" + item.reason.orEmpty() }
                            ?: if (item.candidates.isEmpty()) "В опубликованном каталоге не найдено."
                            else "Варианты для самостоятельного выбора:\n" + item.candidates.joinToString("\n\n") { offerText(it) }
                        "${item.product}: нужно ${item.grams} г\n$choice"
                    }
                    val sources = (data.sources ?: listOf(data.source)).joinToString("\n\n") {
                        "${it.chain}: ${it.message}" + (it.fetchedAt?.let { date -> "\nПолучено: $date" } ?: "")
                    }
                    result.text = "Дни ${data.startDay}–${data.endDay} · ${data.region}\n$status\n\n$rows\n\n$sources\n\n${data.disclaimer}"
                }
                override fun onFailure(call: Call<PlanProductsResponse>, error: Throwable) {
                    if (call.isCanceled) return
                    showLoading(false)
                    result.text = "Не удалось получить товары. Проверьте соединение с сервером."
                }
            })
    }

    private fun formatDistance(value: Int): String =
        if (value < 1000) "$value м" else String.format(Locale.getDefault(), "%.1f км", value / 1000.0)

    private fun showLoading(value: Boolean) {
        progress.visibility = if (value) View.VISIBLE else View.GONE
        compareButton.isEnabled = !value
        planProductsButton.isEnabled = !value
        regionSpinner.isEnabled = !value
        magnitLink.isEnabled = !value
        refreshPrices.isEnabled = !value
    }

    override fun onDestroy() {
        searchCall?.cancel()
        planCall?.cancel()
        locationListener?.let { locationManager.removeUpdates(it) }
        handler.removeCallbacksAndMessages(null)
        super.onDestroy()
    }
}
