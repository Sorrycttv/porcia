package ru.pershin.nutriplan

import com.google.gson.annotations.SerializedName
import retrofit2.Call
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.Body
import retrofit2.http.POST
import retrofit2.http.Header
import retrofit2.http.PUT
import retrofit2.http.GET
import retrofit2.http.Query
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit
import retrofit2.http.DELETE

// Учётные данные для регистрации и входа.
data class RegisterRequest(
    val email: String,
    val password: String
)

// Параметры пользователя, на основании которых рассчитывается рацион.
data class ProfileRequest(
    val sex: String,
    val age: Int,
    @SerializedName("height_cm")
    val heightCm: Double,
    @SerializedName("weight_kg")
    val weightKg: Double,
    val activity: String,
    val goal: String,
    val diet: String,
    val restrictions: List<String>,
    @SerializedName("preferred_foods")
    val preferredFoods: List<String>,
    @SerializedName("target_calories")
    val targetCalories: Double? = null,
    @SerializedName("monthly_budget")
    val monthlyBudget: Double?
)

data class ProfileResponse(
    val profile: ProfileRequest?
)

data class StatusResponse(
    val status: String
)

// Ответ сервера после успешной регистрации или входа.
data class AuthResponse(
    @SerializedName("access_token")
    val accessToken: String,
    @SerializedName("token_type")
    val tokenType: String
)

data class RecipeIngredient(
    val product: String,
    val grams: Double
)

data class RecipeItem(
    val name: String,
    val calories: Int = 0,
    val ingredients: List<RecipeIngredient>,
    @SerializedName("preparation_minutes")
    val preparationMinutes: Int,
    val instructions: String,
    @SerializedName("portion_weight_grams")
    val portionWeightGrams: Int,
    @SerializedName("nutrition_source") val nutritionSource: String? = null,
    @SerializedName("nutrition_status") val nutritionStatus: String? = null,
    @SerializedName("weight_basis") val weightBasis: String? = null,
    @SerializedName("recipe_source_url") val recipeSourceUrl: String? = null,
    @SerializedName("recipe_adaptation_note") val recipeAdaptationNote: String? = null,
    @SerializedName("cooking_water_ml") val cookingWaterMl: Double? = null
)

data class RecipesResponse(
    val recipes: List<RecipeItem>
)

// Один продукт, который пользователь указал в домашнем запасе.
data class PreferenceRequest(val request: String)
data class PlanPreferences(
    val days: Int?,
    @SerializedName("cooking_mode") val cookingMode: String?,
    @SerializedName("desired_ingredients") val desiredIngredients: List<String>,
    @SerializedName("unhandled_requests") val unhandledRequests: List<String>
)
data class PreferenceResponse(val available: Boolean, val preferences: PlanPreferences?, val message: String)

data class PantryItemRequest(
    val product: String,
    val grams: Double
)

data class FridgeResponse(
    val items: List<PantryItemRequest>
)

data class MissingIngredient(
    val product: String,
    val grams: Int
)

data class FridgeRecipe(
    val name: String,
    val calories: Int,
    @SerializedName("portion_weight_grams")
    val portionWeightGrams: Int,
    val missing: List<MissingIngredient>
)

data class FridgeRecommendationsResponse(
    @SerializedName("can_cook")
    val canCook: List<FridgeRecipe>,
    @SerializedName("need_to_buy")
    val needToBuy: List<FridgeRecipe>
)

// генерация рациона
data class PlanRequest(
    val days: Int,
    val pantry: List<PantryItemRequest> = emptyList(),

    @SerializedName("desired_ingredients")
    val desiredIngredients: List<String> = emptyList(),

    @SerializedName("surprise_me")
    val surpriseMe: Boolean,

    @SerializedName("cooking_mode")
    val cookingMode: String,
    @SerializedName("reset_diet")
    val resetDiet: Boolean = true,
    @SerializedName("use_ai")
    val useAi: Boolean = true,
    @SerializedName("menu_wish")
    val menuWish: String = ""
)

// Одно блюдо
data class PlanMeal(
    val meal: String,
    val recipe: String,

    @SerializedName("portion_weight_grams")
    val portionWeightGrams: Int,

    val calories: Int,

    @SerializedName("estimated_cost")
    val estimatedCost: Int,

    @SerializedName("display_minutes")
    val displayMinutes: Int,

    @SerializedName("time_kind")
    val timeKind: String,
    @SerializedName("prepared_on_day")
    val preparedOnDay: Int? = null,
    @SerializedName("batch_servings_to_prepare")
    val batchServingsToPrepare: Int = 1,
    @SerializedName("selection_reasons")
    val selectionReasons: List<String>? = null,
    val ingredients: List<RecipeIngredient>? = null,
    val instructions: String? = null,
    @SerializedName("nutrition_source") val nutritionSource: String? = null,
    @SerializedName("recipe_source_url") val recipeSourceUrl: String? = null,
    @SerializedName("recipe_adaptation_note") val recipeAdaptationNote: String? = null,
    @SerializedName("cooking_water_ml") val cookingWaterMl: Double? = null
)

// меню 1 дня
data class PlanDay(
    val date: String,
    val meals: List<PlanMeal>,

    @SerializedName("estimated_cost")
    val estimatedCost: Int
)

// список покупок
data class ShoppingItem(
    val product: String,
    val grams: Int,

    @SerializedName("packages_to_buy")
    val packagesToBuy: Int,

    @SerializedName("package_grams")
    val packageGrams: Int,
    @SerializedName("expected_leftover_grams")
    val expectedLeftoverGrams: Int = 0
)

data class WeeklyShopping(
    @SerializedName("start_day") val startDay: Int,
    @SerializedName("end_day") val endDay: Int,
    val items: List<ShoppingItem>
)

//ответ сервера
data class PlanResponse(
    @SerializedName("plan_id") val planId: Int? = null,
    val revision: String? = null,
    val replacement: MealReplacementResult? = null,
    val currency: String = "RUB",

    @SerializedName("period_days")
    val periodDays: Int,

    @SerializedName("target_calories")
    val targetCalories: Double,

    val days: List<PlanDay>,

    @SerializedName("shopping_list")
    val shoppingList: List<ShoppingItem>,

    @SerializedName("estimated_period_cost")
    val estimatedPeriodCost: Int,

    @SerializedName("estimated_monthly_cost")
    val estimatedMonthlyCost: Int,
    @SerializedName("cooking_mode")
    val cookingMode: String? = null,
    @SerializedName("weekly_shopping")
    val weeklyShopping: List<WeeklyShopping>? = null,
    @SerializedName("pantry_used")
    val pantryUsed: List<PantryItemRequest>? = null,
    val warnings: List<String>? = null,
    @SerializedName("ai_selection")
    val aiSelection: AiSelection? = null
)

data class AiSelection(
    val status: String,
    @SerializedName("applied_meals") val appliedMeals: Int = 0,
    @SerializedName("requested_meals") val requestedMeals: Int = 0
)

data class MealReplacementRequest(val revision: String,
    @SerializedName("day_index") val dayIndex: Int, val meal: String, val reason: String)
data class MealReplacementResult(@SerializedName("ai_status") val aiStatus: String, val message: String)

data class CurrentPlanResponse(
    val plan: PlanResponse?
)

// вопрос пользователя ИИ-коучу
data class CoachHistoryItem(
    val role: String,
    val content: String
)

data class CoachRequest(
    val message: String,
    val history: List<CoachHistoryItem> = emptyList()
)

// Ответ ИИ
data class CoachResponse(
    val answer: String,

    // true — ответила языковая модель
    // false — сервер вернул резервное объяснение
    val available: Boolean,

    // Варианты следующих вопросов.
    val suggestions: List<String>
)

data class StoreComparisonRequest(
    val latitude: Double,
    val longitude: Double,
    @SerializedName("radius_km") val radiusKm: Double = 5.0,
    val product: String,
    @SerializedName("region_id") val regionId: Int = 1,
    @SerializedName("magnit_shop_code") val magnitShopCode: String? = null,
    @SerializedName("refresh_prices") val refreshPrices: Boolean = false
)

data class NearbyStore(
    val id: String,
    val chain: String,
    val name: String,
    val address: String,
    val latitude: Double,
    val longitude: Double,
    @SerializedName("opening_hours") val openingHours: String?,
    @SerializedName("source_url") val sourceUrl: String?,
    @SerializedName("distance_m") val distanceMeters: Int
)

data class StoreLocationsRequest(
    val latitude: Double,
    val longitude: Double,
    @SerializedName("radius_km") val radiusKm: Double,
    @SerializedName("region_id") val regionId: Int
)

data class StoreLocationSource(val name: String, val available: Boolean,
    val partial: Boolean = false, @SerializedName("coverage_radius_km") val coverageRadiusKm: Double?)

data class StoreLocationsResponse(
    val stores: List<NearbyStore>,
    val sources: List<StoreLocationSource>,
    val status: String,
    val disclaimer: String
)

data class WalkingRouteRequest(
    val latitude: Double,
    val longitude: Double,
    @SerializedName("destination_latitude") val destinationLatitude: Double,
    @SerializedName("destination_longitude") val destinationLongitude: Double
)

data class WalkingRouteResponse(
    val available: Boolean,
    val geometry: List<List<Double>>,
    @SerializedName("distance_m") val distanceMeters: Int?,
    @SerializedName("duration_seconds") val durationSeconds: Int?,
    val message: String
)

data class StorePriceOffer(
    val chain: String,
    val product: String,
    val price: Double,
    val currency: String,
    val `package`: String?,
    @SerializedName("source_url") val sourceUrl: String,
    @SerializedName("valid_from") val validFrom: String?,
    @SerializedName("valid_until") val validUntil: String?,
    @SerializedName("price_per_unit") val pricePerUnit: Double?,
    @SerializedName("package_unit") val packageUnit: String?,
    val region: String?,
    val conditions: String?,
    @SerializedName("store_address") val storeAddress: String?,
    @SerializedName("fetched_at") val fetchedAt: String?,
    @SerializedName("price_scope") val priceScope: String?
)

data class PriceSourceStatus(
    val chain: String,
    val status: String,
    val message: String,
    @SerializedName("fetched_at") val fetchedAt: String?,
    @SerializedName("checked_at") val checkedAt: String?,
    @SerializedName("source_url") val sourceUrl: String?
)

data class StoreComparisonResponse(
    @SerializedName("searched_product") val searchedProduct: String,
    val stores: List<NearbyStore>,
    val offers: List<StorePriceOffer>,
    val sources: List<PriceSourceStatus>,
    @SerializedName("fetched_at") val fetchedAt: String?,
    val region: String?,
    @SerializedName("location_status") val locationStatus: String?,
    val disclaimer: String
)

data class PlanProductsRequest(
    @SerializedName("region_id") val regionId: Int,
    @SerializedName("week_index") val weekIndex: Int = 0,
    @SerializedName("magnit_shop_code") val magnitShopCode: String? = null,
    @SerializedName("refresh_prices") val refreshPrices: Boolean = false
)

data class PlanProductChoice(
    val product: String,
    val grams: Int,
    val candidates: List<StorePriceOffer>,
    val offer: StorePriceOffer?,
    val status: String,
    val reason: String?
)

data class PlanProductsResponse(
    val items: List<PlanProductChoice>,
    @SerializedName("start_day") val startDay: Int,
    @SerializedName("end_day") val endDay: Int,
    val region: String,
    val source: PriceSourceStatus,
    val sources: List<PriceSourceStatus>?,
    val available: Boolean,
    @SerializedName("ai_status") val aiStatus: String,
    val disclaimer: String
)

interface ApiService {
    @POST("api/v1/plans/replace-meal")
    fun replaceMeal(@Header("Authorization") authorization: String,
                    @Body request: MealReplacementRequest): Call<PlanResponse>
    @POST("api/v1/stores/nearby")
    fun nearbyStores(@Header("Authorization") authorization: String,
                     @Body request: StoreLocationsRequest): Call<StoreLocationsResponse>

    @POST("api/v1/stores/walking-route")
    fun walkingRoute(@Header("Authorization") authorization: String,
                     @Body request: WalkingRouteRequest): Call<WalkingRouteResponse>

    // Регистрация
    @POST("api/v1/auth/register")
    fun register(
        @Body request: RegisterRequest
    ): Call<AuthResponse>

    // Вход
    @POST("api/v1/auth/login")
    fun login(
        @Body request: RegisterRequest
    ): Call<AuthResponse>

    @GET("api/v1/recipes")
    fun getRecipes(
        @Header("Authorization") authorization: String,
        @Query("q") query: String? = null
    ): Call<RecipesResponse>

    @POST("api/v1/ai/plan-preferences")
    fun interpretPreferences(@Header("Authorization") authorization: String,
                             @Body request: PreferenceRequest): Call<PreferenceResponse>

    @GET("api/v1/fridge")
    fun getFridge(
        @Header("Authorization") authorization: String
    ): Call<FridgeResponse>

    @PUT("api/v1/fridge")
    fun saveFridge(
        @Header("Authorization") authorization: String,
        @Body items: List<PantryItemRequest>
    ): Call<StatusResponse>

    @GET("api/v1/fridge/recommendations")
    fun getFridgeRecommendations(
        @Header("Authorization") authorization: String
    ): Call<FridgeRecommendationsResponse>

    // вопрос ИИ-коучу
    @POST("api/v1/coach/chat")
    fun sendCoachMessage(
        @Header("Authorization") authorization: String,
        @Body request: CoachRequest
    ): Call<CoachResponse>

    @GET("api/v1/profile")
    fun getProfile(
        @Header("Authorization") authorization: String
    ): Call<ProfileResponse>

    // Сохранение параметров рациона
    @PUT("api/v1/profile")
    fun saveProfile(
        @Header("Authorization")
        authorization: String,
        @Body
        request: ProfileRequest

    ): Call<StatusResponse>

    @POST("api/v1/plans/generate")
    fun generatePlan(
        @Header("Authorization") authorization: String,
        @Body request: PlanRequest
    ): Call<PlanResponse>

    @GET("api/v1/plans/current")
    fun getCurrentPlan(
        @Header("Authorization") authorization: String
    ): Call<CurrentPlanResponse>

    @DELETE("api/v1/plans/current")
    fun clearCurrentPlan(
        @Header("Authorization") authorization: String
    ): Call<StatusResponse>

    @POST("api/v1/stores/compare")
    fun compareStorePrices(
        @Header("Authorization") authorization: String,
        @Body request: StoreComparisonRequest
    ): Call<StoreComparisonResponse>

    @POST("api/v1/stores/plan-products")
    fun findPlanProducts(
        @Header("Authorization") authorization: String,
        @Body request: PlanProductsRequest
    ): Call<PlanProductsResponse>
}

// Единая точка доступа к серверному API.
object ApiClient {
    private val BASE_URL = BuildConfig.API_BASE_URL
    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .build()
    val service: ApiService by lazy {

        Retrofit.Builder()
            .baseUrl(BASE_URL)
            .client(httpClient)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(ApiService::class.java)
    }
}
