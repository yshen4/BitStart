This document discusses several options of Spring Boot IoC for Dependency Injection(DI).

Spring Boot supports DI through the Spring Framework, which implements the core principles of the Inversion of Control (IoC) pattern. DI allows Spring Boot to manage the lifecycle and dependencies of beans (objects) in the application context, ensuring loose coupling and easier testability.

## Types of Dependency Injection

Spring Boot supports three primary types of DI:
1. Constructor Injection: Dependencies are provided via the class constructor
2. Setter Injection: Dependencies are injected via setter methods
3. Field Injection: Dependencies are injected directly into fields using the @Autowired annotation

```java
//Constructor Injection: @Service annotates RbacService, 
// Spring Boot injects UserRepository in contruction
@Service
public class RbacService {
    private final UserRepository userRepository;
    public RbacService(UserRepository repository) {
        this.userRepository = repository;
    }
}
//Setter Injection: @Autowired tells Spring Boot to inject UserRepository
// with setRepository
@Component
public class RbacService {
    private UserRepository userRepository;
    @Autowired
    public void setRepository(UserRepository repository) {
        this.userRepository = repository;
    }
}
//Field Injection: with @Autowired
// Although this is the simpliest optoin, we don't use it because it isn't testable
@Component
public class RbacService {
    @Autowired
    private UserRepository userRepository;
}
```

## Bean Management

A bean is a reusable software component that adheres to specific conventions, which can be managed by the Spring container, and DI. Spring Boot automatically configures and manages beans in the IoC container.

Classes annotated with @Component, @Service, @Repository, or @Controller are automatically detected and registered as beans.

## Customize bean definition using the @Bean annotation in a configuration class.

Annotations Enable Dependency Injection

There are several annotations which enable DI
1. @Autowired: automatically injects a bean by type.
2. @Qualifier: used when there are multiple beans of the same type to specify which one to inject.
3. @Primary: mark a bean as the primary candidate when multiple beans of the same type exist
4. @Value: injects values from the application properties or environment variables.

## Spring Boot-Specific Dependency Injection

Spring Boot scans the classpath and automatically configures beans for common components (like data sources, message queues, etc.).

Adding spring-boot-starter-data-jpa automatically sets up an EntityManagerFactory.

Spring Boot automatically enables @EnableJpaRepositories  if we have the spring-boot-starter-data-jpa dependency.

In Spring Data JPA, interfaces that extend JpaRepository don't need an explicit implementation because Spring Data JPA provides the implementation automatically at runtime. When we extend JpaRepository, Spring Data JPA generates the necessary code for common CRUD operations based on the interface methods, allowing developers to focus on the business logic.

## Spring Boot: bootstrap database with application.properties

There are several ways for SpringBoot to bootstrap the database schema using a combination of JPA (Java Persistence API), Hibernate, and SQL scripts. StarTree uses Flyway to handle migrations safely.

### Using Hibernate Auto DDL (Spring JPA)

When using Spring Data JPA, Spring Boot can automatically manage database schema creation via Hibernate's hibernate.hbm2ddl.auto property.

Spring Boot scans Entity classes (@Entity) and generates tables based on them. Column definitions come from field types and annotations like @Column, @GeneratedValue, etc.

We can configure this in application.properties:
```
# none – No schema generation (default for production).
# update – Updates the schema without dropping existing tables.
# create – Drops and creates the schema at startup.
# create-drop – Creates schema at startup and drops it when the app stops.
# validate – Verifies that the schema matches the entities but does not modify it.
spring.jpa.hibernate.ddl-auto=update
```

### Using SQL Scripts (schema.sql and data.sql)

In this method, we run SQL to bootstrap the database.

```spring.sql.init.mode=always```

### Using Flyway or Liquibase for Database Migrations

StarTree-auth uses Flyway to migrate database schemas.

Step 1: Add dependencies in auth-core pom.xml
```xml
<dependency>
  <groupId>org.flywaydb</groupId>
  <artifactId>flyway-core</artifactId>
</dependency>
<dependency>
  <groupId>org.flywaydb</groupId>
  <artifactId>flyway-mysql</artifactId>
</dependency>
```
Step 2: Create migration files in src/main/resources/db/auth/migration/mariadb

Schema naming must follow the convention: files must be named V<version_number>__<description>.sql, e.g.,
```
V0_1_0_0__Schema_Initialization.sql
V0_2_0_0__Rbac_Tables_Addition.sql
```
Here, `0_1_0_0` and `0_2_0_0` are version numbers, and Schema_Initialization and Rbac_Tables_Addition are descriptions.

Step 3: Enable it in auth-manager-persistence-mariadb.properties
```
# Flyway
spring.flyway.enabled=true
spring.flyway.locations=classpath:db/auth/migration/mariadb
```
Step 4: Launch the application passing in property files

We have to tell Spring Boot to load extra property files manually. There are two main approaches:
1. Use @PropertySource in Each Package-Specific Configuration Class
2. Use spring.config.location Argument

With @PropertySource, we annotate each AutoConfiguration class to tell SpringBoot how to configure the class. For example, in AuthManagerServerAutoConfiguration, we define mariadb profile loading properites from auth-manager-persistence-mariadb.properties. Each package can define their own application.properties.
```java
@Configuration
@Profile("mariadb")
@PropertySource("classpath:auth-manager-persistence-mariadb.properties")
public class MariaDBAutoConfiguration {}
```
With spring.config.location Argument, we pass a comma separated properties file:
1. The --spring.config.location method replaces the default location, 
2. The --spring.config.additional-location adds external files to override the default location
3. @PropertySource is useful for loading specific properties inside configuration classes.

Use profiles if different packages represent different environments.
```shell
--spring.config.location=file:/path/to/package1/application-package1.properties,file:/path/to/package2/application-package2.properties 
```

Here are examples: 
```shell
# Only if override a small number of properties
java -jar "./auth/auth-server/target/auth-server-1.0.0.0-SNAPSHOT.jar" \
"--spring.datasource.url=jdbc:mariadb://localhost:3306/startree_auth_db" \
"--spring.datasource.username=admin" \
"--spring.datasource.password=4056@st" \
"--spring.flyway.enabled=true" \
"--spring.flyway.locations=classpath:db/auth/migration/mariadb"
  
java -jar "./rbac-manager/rbac-manager-server/target/rbac-manager-server-1.0.0.0-SNAPSHOT.jar" \
"--spring.datasource.url=jdbc:mariadb://localhost:3306/startree_auth_db" \
"--spring.datasource.username=admin" \
"--spring.datasource.password=4056@st" \
"--spring.flyway.enabled=true" \
"--spring.flyway.locations=classpath:db/auth/migration/mariadb"

# This is a better option
java -jar "./rbac-manager/rbac-manager-server/target/rbac-manager-server-1.0.0.0-SNAPSHOT.jar --spring.config.location=" \
"file:/Users/yueshen/workspace/tasks/AuthOnBareMetal/mariadb.properties," \
"classpath:startree-auth/auth/auth-core/src/main/resources/auth-manager-persistence-mariadb.properties"
```
Another way is that we export username and password and run it (not recommended because it changes environment variables, which may affect build or other tests):
```shell
export SPRING_DATASOURCE_URL=jdbc:mariadb://localhost:3306/startree_auth_db
export SPRING_DATASOURCE_USERNAME=<your_username>
export SPRING_DATASOURCE_PASSWORD=<your_password>
java -jar startree-auth/rbac-manager/rbac-manager-server/target/rbac-manager-server-1.0.0.0-SNAPSHOT.jar
```

## Case study 1: PolicyRepository

The PolicyRepository interface extends JpaRepository, which provides methods to load data from the database based on the Policy entity. Spring Data JPA automatically generates the implementation for these methods at runtime. The JpaRepository knows where to load the data through the entity class annotations and configuration in the Spring application context.

In StarTree-auth/AuthManagerServerAutoConfiguration, we annotate bean PolicyLoader:
```java
@Bean
PolicyLoader policyLoader(
    PolicyRepository policyRepository, 
    RolePolicyAttachmentRepository rolePolicyAttachmentRepository,
    SubjectRoleAssignmentRepository subjectRoleAssignmentRepository
) {
    return new PolicyLoader(policyRepository, rolePolicyAttachmentRepository, subjectRoleAssignmentRepository);
}
```

PolicyRepository extends JpaRepository<Policy, Long> and JpaSpecificationExecutor<Policy>, which Spring Data JPA automatically generates the implementation for methods at runtime, which uses Policy entity to interact with Policy table in the database:
```java
public interface PolicyRepository extends JpaRepository<Policy, Long>, JpaSpecificationExecutor<Policy> {
    Policy findBySrn(String srn);

    @Transactional
    void deleteBySrn(String srn);
}
```

In class Policy definition, it is annotated with @Entity, which tells JPA that the class is an entity and is mapped to a database table. This annotation is part of the Java Persistence API (JPA), which is a specification for object-relational mapping (ORM) in Java:

Marks the Class as an Entity: By annotating a class with @Entity, we tell JPA that this class should be mapped to a table in the database.

Table Mapping: By default, the class name is used as the table name. However, we can customize this using the @Table annotation.

Primary Key: Typically, an entity class will have a field annotated with @Id to denote the primary key of the table.
```java
@Entity
public class Policy {
    @Id
    Long id;
    String srn;
    String name;
    String description;
    ...
}
```
### Case study 2: AuthN/AuthZ

StarTree-platform/StarTree-auth defines 3 AuthN/AuthZ providers:
1. PlatformBearerTokenAuthenticationProvider: authenticate user identity with Bearer token
2. PlatformStartreeAuthenticationProvider: authenticate user identity with StarTree token
3. PlatformUsernamePasswordAuthenticationProvider: authenticate user identity with password

On Authentication side, AuthManagerServerAutoConfiguration constructs the instance of provider based on the configuration defined in application.properties:
1. PlatformBearerTokenAuthenticationProvider: security.auth.server.provider.oidc.enabled
2. PlatformStartreeAuthenticationProvider: security.auth.server.provider.startree-header.enabled
3. PlatformUsernamePasswordAuthenticationProvider: security.auth.server.provider.basic-user.enabled

On Authorization side, constructs AuthManager instance from AuthManagerImpl based on a flag defined in application.properties:
1. security.auth.server.web.exposed
2. Types of Tokens RBAC/Auth supports

In StarTree, we support 2 types of tokens

StarTree token

OIDC token

OIDC token is a JWT token which contains user email and groups. It is authenticated with PlatformBearerTokenAuthenticationProvider. 

StarTree token starts with st-, which contains access key and hashed secret. Even though passed as token, it is authenticated with PlatformStartreeAuthenticationProvider in which the provider loads the token with access key, and validates the secret against the token, set the user loaded in the token. 

When we authorize this token in AuthManager.authorize function, it iterates subjects associated with the user, including email, domain, and group, look for the roles in the subject-role assignment repository. When we find the roles assigned with the subject, load policies to evaluate.

From Amol and Chris, we have 3 generations of tokens:

Generation

Token

User

Role

Service token

RBAC support

1

StarTree

OIDC

No role

No

No

2

StarTree

Local user

Role assigned to token

Yes

Yes

3

OIDC

OIDC

Role assigned to user email, domain, or group

No

Yes

How does Spring boot parse authN token based on the request header?

In class PlatformAuthenticationFilter, function doFilterInternal calls RestUtils.authentication, passing in request, which determine what tokens are in the request header:
```java
public static AbstractAuthenticationToken authentication(Map<String, String> headers) {
  var authorization = getOrLowerCase(headers, AUTHORIZATION);
  if (StringUtils.isNotBlank(authorization) 
      && authorization.startsWith(PREFIX_BEARER)
  ) {
    var token = authorization.substring(PREFIX_BEARER.length()).strip();
    //If the token starts with "st-", it is startree token
    if (StartreeAuthenticationToken.isStartreeTokenValue(token)) {
      return new StartreeAuthenticationToken(token);
    } else {
      return new BearerTokenAuthenticationToken(token);
    }
  }

  //X-Startree-Token header exists
  var startreeHeader = getOrLowerCase(headers, STARTREE_TOKEN);
  if (StringUtils.isNotBlank(startreeHeader)) {
    return new StartreeAuthenticationToken(startreeHeader.strip());
  }

  //Basic user/password
  if (StringUtils.isNotBlank(authorization) && authorization.startsWith(PREFIX_BASIC)) {
    var decode = new String(Base64.getDecoder().decode(authorization.substring(PREFIX_BASIC.length()))).strip();
    var parts = decode.split(":", 2);
    Assert.isTrue(parts.length == 2, "basic auth requires username:password pair");
    return new UsernamePasswordAuthenticationToken(parts[0], parts[1]);
  }

  return null;
}
```
How does Spring boot choose which authN provider?

In Auth-core, we implement 3 providers:

PlatformBearerTokenAuthenticationProvider

PlatformStartreeAuthenticationProvider

PlatformUsernamePasswordAuthenticationProvider

Each of the provider implements supports function, which check if the authentication is the token this provider supports:

@Override
public boolean supports(Class<?> aClass) {
    return BearerTokenAuthenticationToken.class.isAssignableFrom(aClass);
}

In class ProviderManager its authenticate function iterates all providers, and checks if the token is supported by the provider. If so, authenticate with the token passed in. 

@Override
public Authentication authenticate(Authentication authentication) throws AuthenticationException {
    Class<? extends Authentication> toTest = authentication.getClass();
    for (AuthenticationProvider provider : getProviders()) {
        if (!provider.supports(toTest)) continue;
        try {
            result = provider.authenticate(authentication);
            if (result != null) {
                copyDetails(authentication, result);
                break;
            }
        } catch (AccountStatusException | InternalAuthenticationServiceException ex) {
            prepareException(ex, authentication);
            throw ex;
        }
    }
    if (result != null) return result;
    //throw Exception;
}

Case study 3: HealthIndicator

In Spring Boot, a HealthIndicator is used to check server health with the application's /actuator/health endpoint.

Spring Boot Actuator provides an interface for this function:

public interface HealthIndicator {
    Health health();
}

Enable the Actuator Endpoint

In application.properties, we need to enable the endpoints:

management.endpoints.web.exposure.include=health
management.endpoint.health.show-details=always

We also add the actuator dependency in pom.xml of the application:

<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-actuator</artifactId>
</dependency>

Implement HealthIndicator interface

Spring Boot scans @Component and registers it. On /actuator/health, Spring runs all HealthIndicator beans.

@Slf4j
@Component
public class StartUpHealthIndicator implements HealthIndicator {
    private final DataSource dataSource;

    public StartUpHealthIndicator(DataSource dataSource) {
        this.dataSource = dataSource;
    }

    @Override
    public Health health() {

    }
    
    @Override
    public Health health() {
        // You can log custom startup diagnostics
        log.info("Performing startup health check...");

        boolean healthy = checkStartupCondition();
        if (healthy) {
            return Health.up().withDetail("database", "database connection successful in rbac service").build();
        } else {
            return Health.down().withDetail("database", "unable to connect to database from rbac service").build();
        }
    }

    private boolean checkStartupCondition() {
        try (Connection connection = dataSource.getConnection()) {
            try (Statement statement = connection.createStatement()) {
                ResultSet resultSet = statement.executeQuery("SELECT 1");
                // Timeout of 2 seconds
                if (resultSet.next() && connection.isValid(2)) { 
                    return true;
                } else {
                    log.warn("unable to connect to database from rbac service");
                    return false;
                }
            }
        } catch (SQLException e) {
            log.warn("startup probe failed unable to connect to database from rbac service", e);
            return false;
        }
    }
}

Check the service health

application.properties:

management.endpoints.web.exposure.include=auditevents,info,health,httptrace,prometheus,metrics,configprops,beans,conditions,env

# metrics
management.server.port=8081

# Health configuration
management.endpoint.health.show-details=always
management.endpoint.health.show-components=always
management.endpoint.health.probes.enabled=true

# Liveness group configuration
management.endpoint.health.group.liveness.include=livenessState,db,startUp
management.endpoint.health.group.liveness.show-details=always
management.endpoint.health.group.liveness.show-components=always

# Readiness group configuration
management.endpoint.health.group.readiness.include=readinessState,db,startUp
management.endpoint.health.group.readiness.show-details=always
management.endpoint.health.group.readiness.show-components=always

We set the Kubernetes template to check service health. For example, startree-core has the following check: 

livenessProbe:
  httpGet:
    path: /actuator/health/liveness
    port: {{ .Values.probes.port }}
    scheme: HTTP
  initialDelaySeconds: 30
  periodSeconds: 5
readinessProbe:
  httpGet:
    path: /actuator/health/readiness
    port: {{ .Values.probes.port }}
    scheme: HTTP
  initialDelaySeconds: 30
  periodSeconds: 5

If we run it locally, we can query AuthServier (port 8081), and Rbac-manager(port 8082). 

# http://localhost:8082/actuator/health/readiness
{
  "status": "UP",
  "components": {
    "db": {
      "status": "UP",
      "details": {
        "database": "MariaDB",
        "validationQuery": "isValid()"
      }
    },
    "readinessState": {
      "status": "UP"
    },
    "startUp": {
      "status": "UP",
      "details": {
        "database": "database connection successful in rbac service"
      }
    }
  }
}

# http://localhost:8081/actuator/health/liveness
{
  "status": "UP",
  "components": {
    "db": {
      "status": "UP",
      "details": {
        "database": "MariaDB",
        "validationQuery": "isValid()"
      }
    },
    "livenessState": {
      "status": "UP"
    },
    "startUp": {
      "status": "UP",
      "details": {
        "database": "database connection successful in auth service"
      }
    }
  }
}

