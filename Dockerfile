FROM maven:3.9.9-eclipse-temurin-17 AS build
WORKDIR /workspace
COPY pom.xml .
COPY orchestrator/pom.xml orchestrator/pom.xml
COPY cart-service/pom.xml cart-service/pom.xml
COPY order-service/pom.xml order-service/pom.xml
COPY payment-simulator/pom.xml payment-simulator/pom.xml
COPY merchant-simulator/pom.xml merchant-simulator/pom.xml
COPY orchestrator/src orchestrator/src
COPY cart-service/src cart-service/src
COPY order-service/src order-service/src
COPY payment-simulator/src payment-simulator/src
COPY merchant-simulator/src merchant-simulator/src
ARG MODULE
RUN mvn -pl ${MODULE} -am -DskipTests package spring-boot:repackage

FROM eclipse-temurin:17-jre-jammy
WORKDIR /app
ARG MODULE
COPY --from=build /workspace/${MODULE}/target/${MODULE}-0.1.0-SNAPSHOT.jar /app/app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
