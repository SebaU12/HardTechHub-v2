import os from "os";
import os from "os";
import Fastify from "fastify";
import swagger from "@fastify/swagger";
import swaggerUi from "@fastify/swagger-ui";
import { Pool } from "pg";

import { publishEvent } from "./event-publisher";
import { buildEvent } from "./events";

const pool = new Pool({
  host: process.env.POSTGRES_HOST ?? "postgres",
  port: parseInt(process.env.POSTGRES_PORT ?? "5432"),
  database: process.env.POSTGRES_DB ?? "hardtech_catalog",
  user: process.env.POSTGRES_USER ?? "hardtech",
  password: process.env.POSTGRES_PASSWORD ?? "hardtech",
});

const app = Fastify({ logger: true });

// Health 
app.get(
  "/health",
  {
    schema: {
      tags: ["health"],
      summary: "Estado del servicio",
      response: {
        200: {
          type: "object",
          properties: {
            service: { type: "string" },
            status: { type: "string" },
            version: { type: "string" },
            instance: { type: "string" },
            instance: { type: "string" },
          },
        },
      },
    },
  },
  async () => ({
    service: "catalog-service",
    status: "healthy",
    version: "1.0.0",
    instance: process.env.INSTANCE_ID ?? os.hostname(),
  })
);

// Products 
const productSchema = {
  type: "object",
  properties: {
    id: { type: "integer" },
    sku: { type: "string" },
    name: { type: "string" },
    description: { type: "string" },
    price: { type: "string" },
    specs: { type: "object", additionalProperties: true },
    image_url: { type: "string" },
    category: { type: "string" },
    brand: { type: "string" },
  },
};

async function findProduct(id: number): Promise<Record<string, unknown> | undefined> {
  const { rows } = await pool.query(
    `SELECT p.id, p.sku, p.name, p.description, p.price, p.specs, p.image_url,
            p.is_active, p.created_at, c.name AS category, b.name AS brand
     FROM products p
     JOIN categories c ON c.id = p.category_id
     JOIN brands b ON b.id = p.brand_id
     WHERE p.id = $1`,
    [id]
  );
  return rows[0] as Record<string, unknown> | undefined;
}

function catalogEventPayload(product: Record<string, unknown>): Record<string, unknown> {
  return {
    sku: product.sku,
    name: product.name,
    category: product.category,
    brand: product.brand,
    price: String(product.price),
  };
}

app.get(
  "/api/products",
  {
    schema: {
      tags: ["products"],
      summary: "Listar productos activos",
      response: { 200: { type: "array", items: productSchema } },
    },
  },
  async (_req, reply) => {
    const { rows } = await pool.query(`
      SELECT p.id, p.sku, p.name, p.description, p.price, p.specs, p.image_url,
             c.name AS category, b.name AS brand
      FROM products p
      JOIN categories c ON c.id = p.category_id
      JOIN brands b ON b.id = p.brand_id
      WHERE p.is_active = TRUE
      ORDER BY p.id ASC
    `);
    return reply.send(rows);
  }
);

app.get<{ Params: { id: string } }>(
  "/api/products/:id",
  {
    schema: {
      tags: ["products"],
      summary: "Obtener detalle de un producto",
      params: {
        type: "object",
        properties: { id: { type: "string", description: "ID del producto" } },
      },
      response: {
        200: {
          ...productSchema,
          properties: {
            ...productSchema.properties,
            is_active: { type: "boolean" },
            created_at: { type: "string" },
          },
        },
        404: { type: "object", properties: { detail: { type: "string" } } },
      },
    },
  },
  async (req, reply) => {
    const id = parseInt(req.params.id);
    if (isNaN(id)) return reply.status(400).send({ detail: "Invalid product id" });
    const product = await findProduct(id);
    if (!product) return reply.status(404).send({ detail: "Product not found" });
    return reply.send(product);
  }
);

app.post(
  "/api/products",
  {
    schema: {
      tags: ["products"],
      summary: "Crear un producto (admin)",
      body: {
        type: "object",
        required: ["category_id", "brand_id", "sku", "name", "price"],
        properties: {
          category_id: { type: "integer" },
          brand_id: { type: "integer" },
          sku: { type: "string" },
          name: { type: "string" },
          description: { type: "string" },
          price: { type: "number" },
          specs: { type: "object", additionalProperties: true },
          image_url: { type: "string" },
        },
      },
      response: {
        201: {
          type: "object",
          properties: {
            id: { type: "integer" },
            sku: { type: "string" },
            name: { type: "string" },
            price: { type: "string" },
            event_published: { type: "boolean" },
            event_key: { type: ["string", "null"] },
          },
        },
      },
    },
  },
  async (req, reply) => {
    const { category_id, brand_id, sku, name, description, price, specs, image_url } =
      req.body as Record<string, unknown>;
    const { rows } = await pool.query(
      `INSERT INTO products (category_id, brand_id, sku, name, description, price, specs, image_url)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
       RETURNING id, sku, name, price`,
      [category_id, brand_id, sku, name, description, price, JSON.stringify(specs), image_url]
    );
    const created = await findProduct(Number(rows[0].id));
    if (!created) return reply.status(500).send({ detail: "Created product could not be loaded" });

    const event = buildEvent(
      "PRODUCT_CREATED",
      "catalog-service",
      {
        ...catalogEventPayload(created),
        specs: created.specs,
      },
      { productId: Number(created.id) }
    );
    const eventKey = await publishEvent(event);
    return reply.status(201).send({
      ...rows[0],
      event_published: eventKey !== null,
      event_key: eventKey,
    });
  }
);

app.put<{ Params: { id: string } }>(
  "/api/products/:id",
  {
    schema: {
      tags: ["products"],
      summary: "Actualizar un producto",
      params: { type: "object", properties: { id: { type: "string" } } },
      body: {
        type: "object",
        properties: {
          name: { type: "string" },
          description: { type: "string" },
          price: { type: "number" },
          specs: { type: "object", additionalProperties: true },
          image_url: { type: "string" },
          is_active: { type: "boolean" },
        },
      },
      response: {
        200: {
          type: "object",
          properties: {
            updated: { type: "boolean" },
            event_published: { type: "boolean" },
            event_keys: { type: "array", items: { type: "string" } },
          },
        },
        404: { type: "object", properties: { detail: { type: "string" } } },
      },
    },
  },
  async (req, reply) => {
    const id = parseInt(req.params.id);
    if (isNaN(id)) return reply.status(400).send({ detail: "Invalid product id" });
    const previous = await findProduct(id);
    if (!previous) return reply.status(404).send({ detail: "Product not found" });

    const { name, description, price, specs, image_url, is_active } =
      req.body as Record<string, unknown>;
    const { rowCount } = await pool.query(
      `UPDATE products SET name=$1, description=$2, price=$3, specs=$4, image_url=$5, is_active=$6 WHERE id=$7`,
      [name, description, price, JSON.stringify(specs), image_url, is_active, id]
    );
    if (rowCount === 0) return reply.status(404).send({ detail: "Product not found" });

    const updated = await findProduct(id);
    if (!updated) return reply.status(500).send({ detail: "Updated product could not be loaded" });

    const events = [
      buildEvent(
        "PRODUCT_UPDATED",
        "catalog-service",
        {
          ...catalogEventPayload(updated),
          updated_fields: Object.keys(req.body as Record<string, unknown>),
        },
        { productId: id }
      ),
    ];

    if (Number(previous.price) !== Number(updated.price)) {
      events.push(
        buildEvent(
          "PRODUCT_PRICE_CHANGED",
          "catalog-service",
          {
            sku: updated.sku,
            category: updated.category,
            brand: updated.brand,
            previous_price: String(previous.price),
            new_price: String(updated.price),
          },
          { productId: id }
        )
      );
    }

    const publishedKeys = await Promise.all(events.map(publishEvent));
    const eventKeys = publishedKeys.filter((key): key is string => key !== null);
    return reply.send({
      updated: true,
      event_published: eventKeys.length === events.length,
      event_keys: eventKeys,
    });
  }
);

app.delete<{ Params: { id: string } }>(
  "/api/products/:id",
  {
    schema: {
      tags: ["products"],
      summary: "Desactivar un producto",
      params: { type: "object", properties: { id: { type: "string" } } },
      response: {
        200: {
          type: "object",
          properties: {
            deleted: { type: "boolean" },
            event_published: { type: "boolean" },
            event_key: { type: ["string", "null"] },
          },
        },
        404: { type: "object", properties: { detail: { type: "string" } } },
      },
    },
  },
  async (req, reply) => {
    const id = parseInt(req.params.id);
    if (isNaN(id)) return reply.status(400).send({ detail: "Invalid product id" });
    const product = await findProduct(id);
    if (!product) return reply.status(404).send({ detail: "Product not found" });

    await pool.query("UPDATE products SET is_active=FALSE WHERE id=$1", [id]);
    const event = buildEvent(
      "PRODUCT_DEACTIVATED",
      "catalog-service",
      catalogEventPayload(product),
      { productId: id }
    );
    const eventKey = await publishEvent(event);
    return reply.send({
      deleted: true,
      event_published: eventKey !== null,
      event_key: eventKey,
    });
  }
);

const start = async () => {
  const apiBaseUrl = process.env.API_BASE_URL?.trim() ?? "";

  await app.register(swagger, {
    openapi: {
      info: {
        title: "Catalog Service",
        description: "Gestión de productos, categorías y marcas de HardTech Hub",
        version: "1.0.0",
      },
      servers: apiBaseUrl ? [{ url: apiBaseUrl, description: "API Gateway / Local" }] : [],
      tags: [
        { name: "health", description: "Estado del servicio" },
        { name: "products", description: "Operaciones sobre productos" },
      ],
    },
  });

  await app.register(swaggerUi, {
    routePrefix: "/catalog/docs",
    uiConfig: { docExpansion: "list" },
  });

  try {
    await app.listen({ port: 8002, host: "0.0.0.0" });
  } catch (err) {
    app.log.error(err);
    process.exit(1);
  }
};

start();
